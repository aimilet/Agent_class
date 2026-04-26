from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.config import get_settings
from backend.models import ReviewJob, Student, Submission, SubmissionLog
from backend.schemas import ManualReviewUpdate, ReviewJobCreate
from backend.services.document_parser import DocumentParser
from backend.services.llm_utils import clamp_score
from backend.services.rename_service import find_best_student_match, normalize_text
from backend.services.review_graph import ReviewWorkflow
from backend.services.submission_bundle import SubmissionBundleParser


@dataclass(slots=True)
class StudentMatchResult:
    student: Student | None
    method: str
    confidence: float
    matched_student_name: str | None
    reason: str


class ReviewService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.parser = DocumentParser()
        self.bundle_parser = SubmissionBundleParser(self.parser, self.settings)
        self.workflow = ReviewWorkflow()

    def _expand_submission_paths(self, raw_paths: list[str]) -> list[Path]:
        files: list[Path] = []
        for raw_path in raw_paths:
            path = Path(raw_path).expanduser().resolve()
            if not path.exists():
                raise ValueError(f"提交路径不存在：{path}")
            if path.is_dir():
                children = sorted(child for child in path.iterdir() if not child.name.startswith("."))
                if self._looks_like_submission_container(children):
                    files.extend(children)
                else:
                    files.append(path)
            else:
                files.append(path)
        unique: list[Path] = []
        seen: set[Path] = set()
        for file_path in files:
            if file_path in seen:
                continue
            seen.add(file_path)
            unique.append(file_path)
        return unique

    def _looks_like_submission_container(self, children: list[Path]) -> bool:
        if not children:
            return False
        if any(child.is_dir() for child in children):
            return True
        if any(child.suffix.lower() in {".zip", ".tar", ".tgz", ".tbz", ".tbz2", ".txz", ".rar", ".7z"} for child in children):
            return True
        return len(children) >= 8

    def _resolve_material_text(
        self,
        direct_text: str | None,
        source_paths: list[str],
        label: str,
    ) -> str | None:
        segments: list[str] = []
        if direct_text and direct_text.strip():
            segments.append(direct_text.strip())

        for raw_path in source_paths:
            bundle = self.bundle_parser.parse_submission(raw_path)
            material_title = Path(raw_path).expanduser().resolve().name
            material_text = bundle.text.strip()
            if material_text:
                segments.append(f"[{label}材料] {material_title}\n{material_text}")

        combined = "\n\n".join(segment for segment in segments if segment.strip())
        return combined or None

    def get_job(self, session: Session, job_id: int) -> ReviewJob | None:
        statement = (
            select(ReviewJob)
            .options(selectinload(ReviewJob.submissions))
            .where(ReviewJob.id == job_id)
        )
        return session.scalar(statement)

    def list_jobs(self, session: Session) -> list[ReviewJob]:
        statement = (
            select(ReviewJob)
            .options(selectinload(ReviewJob.submissions))
            .order_by(ReviewJob.created_at.desc())
        )
        return list(session.scalars(statement).all())

    def get_submission_logs(self, session: Session, submission_id: int) -> list[SubmissionLog]:
        statement = (
            select(SubmissionLog)
            .where(SubmissionLog.submission_id == submission_id)
            .order_by(SubmissionLog.created_at.asc(), SubmissionLog.id.asc())
        )
        return list(session.scalars(statement).all())

    def get_submission(self, session: Session, submission_id: int) -> Submission | None:
        return session.get(Submission, submission_id)

    def create_job(self, session: Session, payload: ReviewJobCreate) -> ReviewJob:
        files = self._expand_submission_paths(payload.submission_paths)
        if not files:
            raise ValueError("没有找到任何待审阅文件。")

        question_text = self._resolve_material_text(payload.question, payload.question_paths, "题目")
        if not question_text:
            raise ValueError("题目内容为空。")
        reference_answer_text = self._resolve_material_text(
            payload.reference_answer,
            payload.reference_answer_paths,
            "参考答案",
        )

        job = ReviewJob(
            title=payload.title,
            question=question_text,
            reference_answer=reference_answer_text,
            rubric=payload.rubric,
            document_parse_mode=payload.document_parse_mode,
            score_scale=payload.score_scale,
            status="pending",
        )
        session.add(job)
        session.flush()

        for file_path in files:
            session.add(
                Submission(
                    review_job_id=job.id,
                    original_filename=file_path.name,
                    stored_path=str(file_path),
                    status="pending",
                    score_scale=payload.score_scale,
                )
            )

        session.commit()
        return self.get_job(session, job.id)  # type: ignore[return-value]

    def _write_log(
        self,
        session: Session,
        submission_id: int,
        stage: str,
        message: str,
        *,
        level: str = "info",
        payload: dict | None = None,
    ) -> None:
        session.add(
            SubmissionLog(
                submission_id=submission_id,
                stage=stage,
                level=level,
                message=message,
                payload=payload,
            )
        )
        session.commit()

    def _match_from_content(self, parsed_text: str, students: list[Student]) -> StudentMatchResult:
        normalized_text = normalize_text(parsed_text)
        if not normalized_text:
            return StudentMatchResult(None, "unmatched", 0.0, None, "正文为空，无法内容匹配")

        student_no_hits = [
            student
            for student in students
            if student.student_no and normalize_text(student.student_no) in normalized_text
        ]
        if len(student_no_hits) == 1:
            student = student_no_hits[0]
            return StudentMatchResult(student, "content_student_no", 98.0, student.name, "正文中命中学号")

        name_hits = [
            student
            for student in students
            if normalize_text(student.name) and normalize_text(student.name) in normalized_text
        ]
        if len(name_hits) == 1:
            student = name_hits[0]
            return StudentMatchResult(student, "content_name", 90.0, student.name, "正文中命中姓名")

        return StudentMatchResult(None, "unmatched", 0.0, None, "正文内容未唯一命中学生")

    def _match_student(
        self,
        filename_stem: str,
        parsed_text: str,
        students: list[Student],
    ) -> StudentMatchResult:
        student, confidence, reason = find_best_student_match(filename_stem, students, threshold=76.0)
        if student is not None:
            method = "filename_exact" if confidence >= 100 else "filename_fuzzy"
            return StudentMatchResult(student, method, round(confidence, 2), student.name, reason or "文件名匹配")

        content_result = self._match_from_content(parsed_text, students)
        if content_result.student is not None:
            return content_result

        return StudentMatchResult(None, "unmatched", 0.0, None, reason or content_result.reason)

    def _select_review_mode(self, job: ReviewJob, submission: Submission) -> tuple[str, str]:
        parse_mode = job.document_parse_mode
        suffix = Path(submission.stored_path).suffix.lower()
        has_visual_assets = bool(submission.images_detected)
        is_direct_image = suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}

        if parse_mode == "local_ocr":
            return "text", "已显式选择本地 OCR / 文本审阅"

        if not self.settings.llm_enabled:
            return "text", "未配置大模型，自动回退到本地 OCR / 文本审阅"

        if parse_mode == "agent_vision":
            if is_direct_image or has_visual_assets:
                return "vision", "已显式选择视觉评分"
            return "text", "当前文件没有可直接送入视觉评分的图像资产，已回退文本审阅"

        if is_direct_image or (has_visual_assets and not (submission.parsed_text or "").strip()):
            return "vision", "自动模式检测到图像型作业，已切换视觉评分"
        return "text", "自动模式保留本地 OCR / 文本审阅"

    def run_job(self, session: Session, job_id: int) -> ReviewJob:
        job = self.get_job(session, job_id)
        if job is None:
            raise ValueError("审阅任务不存在。")

        job.status = "running"
        session.commit()

        students = list(session.scalars(select(Student)).all())
        resolved_reference = self.workflow.resolve_reference_answer(
            job.question,
            job.rubric,
            job.reference_answer,
        )
        reference_source = "provided" if job.reference_answer else "agent_generated"
        if not job.reference_answer:
            job.reference_answer = resolved_reference
            session.commit()

        has_failed = False
        for submission in job.submissions:
            try:
                self._write_log(
                    session,
                    submission.id,
                    "submission_start",
                    "开始处理作业",
                    payload={"stored_path": submission.stored_path},
                )
                bundle = self.bundle_parser.parse_submission(submission.stored_path)
                submission.parser_name = bundle.parser_name
                submission.parsed_text = bundle.text
                submission.parser_notes = bundle.notes
                submission.images_detected = bundle.images_detected
                submission.score_scale = job.score_scale
                session.commit()
                for log in bundle.logs:
                    self._write_log(
                        session,
                        submission.id,
                        log.stage,
                        log.message,
                        level=log.level,
                        payload=log.payload,
                    )
                self._write_log(
                    session,
                    submission.id,
                    "document_parse",
                    "完成文档解析",
                    payload={
                        "parser_name": bundle.parser_name,
                        "images_detected": bundle.images_detected,
                        "notes": bundle.notes,
                        "visual_assets": len(bundle.visual_assets),
                        "included_files": bundle.included_files,
                    },
                )

                match_result = self._match_student(
                    Path(submission.original_filename).stem,
                    bundle.text,
                    students,
                )
                if match_result.student is not None:
                    submission.student_id = match_result.student.id
                    submission.matched_student_name = match_result.student.name
                else:
                    submission.student_id = None
                    submission.matched_student_name = match_result.matched_student_name
                submission.student_match_method = match_result.method
                submission.student_match_confidence = match_result.confidence
                session.commit()
                self._write_log(
                    session,
                    submission.id,
                    "student_match",
                    "完成学生归属判定",
                    level="warning" if match_result.student is None else "info",
                    payload={
                        "student_id": submission.student_id,
                        "matched_student_name": submission.matched_student_name,
                        "method": match_result.method,
                        "confidence": match_result.confidence,
                        "reason": match_result.reason,
                    },
                )
                self._write_log(
                    session,
                    submission.id,
                    "reference_prepare",
                    "参考答案准备完成",
                    payload={
                        "source": reference_source,
                        "reference_preview": resolved_reference[:500],
                    },
                )

                review_mode, review_reason = self._select_review_mode(job, submission)
                self._write_log(
                    session,
                    submission.id,
                    "review_mode_select",
                    "已确定审阅模式",
                    payload={"mode": review_mode, "reason": review_reason},
                )

                review_payload = self.workflow.run(
                    question=job.question,
                    rubric=job.rubric,
                    reference_answer=job.reference_answer,
                    submission_text=bundle.text,
                    parser_notes=bundle.notes,
                    review_mode=review_mode,
                    visual_assets=bundle.visual_assets,
                )
                score = clamp_score(review_payload.get("score", 0))
                review_payload["score"] = score
                review_payload["score_scale"] = job.score_scale
                review_payload["student_id"] = submission.student_id
                review_payload["matched_student_name"] = submission.matched_student_name
                submission.score = score
                submission.review_status = "auto_reviewed"
                submission.review_summary = str(review_payload.get("summary", ""))
                submission.review_payload = review_payload
                submission.status = "completed"
                session.commit()
                self._write_log(
                    session,
                    submission.id,
                    "review",
                    "完成作业评审",
                    payload={
                        "review_mode": review_payload.get("review_mode", review_mode),
                        "decision": review_payload.get("decision"),
                        "score": score,
                        "summary": submission.review_summary,
                    },
                )
                self._write_log(
                    session,
                    submission.id,
                    "score_finalize",
                    "完成分数归一化",
                    payload={"score": score, "score_scale": job.score_scale},
                )
            except Exception as exc:
                has_failed = True
                submission.status = "failed"
                submission.score_scale = job.score_scale
                submission.review_summary = f"处理失败：{exc}"
                submission.review_payload = {"error": str(exc)}
                session.commit()
                self._write_log(
                    session,
                    submission.id,
                    "error",
                    "处理失败",
                    level="error",
                    payload={"error": str(exc)},
                )

        job.status = "partial_failed" if has_failed else "completed"
        session.commit()
        return self.get_job(session, job_id)  # type: ignore[return-value]

    def apply_manual_review(
        self,
        session: Session,
        submission_id: int,
        payload: ManualReviewUpdate,
    ) -> Submission:
        submission = self.get_submission(session, submission_id)
        if submission is None:
            raise ValueError("作业提交不存在。")

        submission.score = clamp_score(payload.score)
        submission.review_summary = payload.review_summary.strip()
        submission.teacher_comment = payload.teacher_comment.strip() if payload.teacher_comment else None
        submission.review_status = payload.review_status
        submission.status = "completed"

        review_payload = dict(submission.review_payload or {})
        review_payload["score"] = submission.score
        review_payload["score_scale"] = submission.score_scale
        review_payload["summary"] = submission.review_summary
        review_payload["teacher_comment"] = submission.teacher_comment
        review_payload["manual_review"] = {
            "review_status": submission.review_status,
            "teacher_comment": submission.teacher_comment,
        }
        submission.review_payload = review_payload
        session.commit()

        self._write_log(
            session,
            submission.id,
            "manual_review",
            "已保存人工复核结果",
            payload={
                "score": submission.score,
                "review_status": submission.review_status,
                "teacher_comment": submission.teacher_comment,
            },
        )
        return submission
