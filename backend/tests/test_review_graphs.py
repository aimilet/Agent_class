from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.db.base import Base
from backend.core.runtime_review_settings import RuntimeReviewSettings
from backend.domain.models import (
    Assignment,
    ApprovalTask,
    Course,
    CourseEnrollment,
    Person,
    ReviewPrep,
    ReviewQuestionItem,
    ReviewResult,
    ReviewRun,
    Submission,
)
from backend.services.document_parser import ParsedDocument, VisualAsset
from backend.services.approvals import ApprovalService
from backend.services.courses import CourseService
from backend.services.review_run import ReviewRunService
from backend.graphs.review_run_parent_graph import ReviewRunParentGraph
from backend.graphs.submission_review_graph import SubmissionReviewGraph


def build_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()


def seed_review_context(session: Session) -> tuple[ReviewRun, Submission, Submission]:
    course = Course(
        public_id=Course.build_public_id(),
        course_code="CS101",
        course_name="程序设计",
        term="2026 春",
        class_label="1班",
        status="active",
    )
    person_a = Person(
        public_id=Person.build_public_id(),
        student_no_raw="2026001",
        student_no_norm="2026001",
        name_raw="张三",
        name_norm="张三",
    )
    person_b = Person(
        public_id=Person.build_public_id(),
        student_no_raw="2026002",
        student_no_norm="2026002",
        name_raw="李四",
        name_norm="李四",
    )
    enrollment_a = CourseEnrollment(
        public_id=CourseEnrollment.build_public_id(),
        course=course,
        person=person_a,
        display_student_no="2026001",
        display_name="张三",
        status="active",
    )
    enrollment_b = CourseEnrollment(
        public_id=CourseEnrollment.build_public_id(),
        course=course,
        person=person_b,
        display_student_no="2026002",
        display_name="李四",
        status="active",
    )
    assignment = Assignment(
        public_id=Assignment.build_public_id(),
        course=course,
        seq_no=1,
        title="第一次作业",
        slug="hw1",
        status="review_prep_ready",
    )
    session.add_all([course, person_a, person_b, enrollment_a, enrollment_b, assignment])
    session.commit()

    review_prep = ReviewPrep(
        public_id=ReviewPrep.build_public_id(),
        assignment_id=assignment.id,
        status="ready",
        version_no=1,
        source_materials_json=[],
    )
    session.add(review_prep)
    session.commit()

    assignment.review_prep_id = review_prep.id
    session.add(assignment)
    session.commit()

    question_item = ReviewQuestionItem(
        public_id=ReviewQuestionItem.build_public_id(),
        review_prep=review_prep,
        question_no=1,
        question_full_text="实现一个排序算法。",
        reference_answer_short="给出正确排序逻辑。",
        reference_answer_full="完整说明排序思路与实现细节。",
        rubric_text="正确性优先。",
        score_weight=1.0,
        status="confirmed",
    )
    review_run = ReviewRun(
        public_id=ReviewRun.build_public_id(),
        assignment=assignment,
        review_prep=review_prep,
        status="queued",
        parallelism=1,
    )
    submission_a = Submission(
        public_id=Submission.build_public_id(),
        assignment=assignment,
        enrollment=enrollment_a,
        source_entry_name="张三-第一次作业",
        source_entry_path="/tmp/sub_a",
        status="review_ready",
        current_path="/tmp/sub_a",
    )
    submission_b = Submission(
        public_id=Submission.build_public_id(),
        assignment=assignment,
        enrollment=enrollment_b,
        source_entry_name="李四-第一次作业",
        source_entry_path="/tmp/sub_b",
        status="review_ready",
        current_path="/tmp/sub_b",
    )
    session.add_all(
        [
            review_prep,
            question_item,
            review_run,
            submission_a,
            submission_b,
        ]
    )
    session.commit()
    return review_run, submission_a, submission_b


def test_submission_review_graph_degrades_invalid_output_to_manual_review(monkeypatch):
    session = build_session()
    review_run, submission, _ = seed_review_context(session)
    graph = SubmissionReviewGraph(session)
    graph.compiled = None

    monkeypatch.setattr(
        graph,
        "select_assets",
        lambda state: {**state, "selected_assets": [], "ignored_assets": []},
    )
    monkeypatch.setattr(
        graph,
        "parse_assets",
        lambda state: {**state, "submission_text": "这是学生提交内容"},
    )

    def explode(state):
        raise ValueError("item_results.0.score 必须大于等于 0")

    monkeypatch.setattr(graph, "grade_submission", explode)

    result_state = graph.invoke(
        review_run_public_id=review_run.public_id,
        submission_public_id=submission.public_id,
        operator_id="tester",
    )

    review_result = session.scalar(
        select(ReviewResult).where(
            ReviewResult.review_run_id == review_run.id,
            ReviewResult.submission_id == submission.id,
        )
    )

    assert result_state["validation_output"]["status"] == "needs_manual_review"
    assert review_result is not None
    assert review_result.status == "needs_manual_review"
    assert "人工复核" in (review_result.summary or "")
    assert review_result.result_json["fallback_reason"] == "submission_review_graph_failed"
    session.refresh(submission)
    assert submission.status == "review_ready"


def test_review_run_parent_graph_continues_after_child_failure():
    session = build_session()
    review_run, submission_a, submission_b = seed_review_context(session)
    graph = ReviewRunParentGraph(session)

    class FakeChildGraph:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.fallback_calls: list[str] = []

        def invoke(self, *, review_run_public_id: str, submission_public_id: str, operator_id: str = "system"):
            self.calls.append(submission_public_id)
            if submission_public_id == submission_a.public_id:
                raise RuntimeError("首份作业评分输出非法")
            return {"validation_output": {"status": "validated"}}

        def mark_submission_for_manual_review(self, *, state, error_message: str, reason: str):
            self.fallback_calls.append(state["submission_public_id"])
            return {
                **state,
                "grading_output": {"summary": error_message},
                "validation_output": {"status": "needs_manual_review", "errors": [error_message]},
            }

    fake_child = FakeChildGraph()
    graph.child_graph = fake_child

    next_state = graph.run_children(
        {
            "review_run_public_id": review_run.public_id,
            "operator_id": "tester",
            "submission_public_ids": [submission_a.public_id, submission_b.public_id],
            "completed_results": 0,
            "manual_review_results": 0,
        }
    )

    assert fake_child.calls == [submission_a.public_id, submission_b.public_id]
    assert fake_child.fallback_calls == [submission_a.public_id]
    assert next_state["completed_results"] == 1
    assert next_state["manual_review_results"] == 1


def test_review_run_parent_graph_finalize_uses_fresh_result_query():
    session = build_session()
    review_run, submission_a, submission_b = seed_review_context(session)
    graph = ReviewRunParentGraph(session)

    # 模拟关系缓存仍为空但数据库已有结果的场景，避免完成统计写成 0。
    _ = review_run.results
    session.add_all(
        [
            ReviewResult(
                public_id=ReviewResult.build_public_id(),
                review_run_id=review_run.id,
                submission_id=submission_a.id,
                total_score=88.0,
                score_scale=100,
                summary="张三评分完成",
                status="validated",
            ),
            ReviewResult(
                public_id=ReviewResult.build_public_id(),
                review_run_id=review_run.id,
                submission_id=submission_b.id,
                total_score=76.0,
                score_scale=100,
                summary="李四评分完成",
                status="validated",
            ),
        ]
    )
    session.commit()

    graph.finalize_run({"review_run_public_id": review_run.public_id, "operator_id": "tester"})

    session.refresh(review_run)
    assert review_run.status == "completed"
    assert review_run.summary_json == {
        "result_count": 2,
        "validated_count": 2,
        "manual_review_count": 0,
    }


def test_course_review_summary_includes_finalized_results():
    session = build_session()
    review_run, submission, _ = seed_review_context(session)
    session.add(
        ReviewResult(
            public_id=ReviewResult.build_public_id(),
            review_run_id=review_run.id,
            submission_id=submission.id,
            total_score=74.0,
            score_scale=100,
            summary="最终评分说明",
            status="finalized",
        )
    )
    session.commit()

    payload = CourseService(session).get_review_summary(review_run.assignment.course.public_id)
    first_row = payload["rows"][0]
    first_cell = first_row["results"][0]

    assert first_row["student_no"] == "2026001"
    assert first_cell["score"] == 74.0
    assert first_cell["summary"] == "最终评分说明"
    assert first_cell["status"] == "finalized"


def test_course_review_summary_prefers_published_result_over_finalized_result():
    session = build_session()
    review_run, submission, _ = seed_review_context(session)
    second_run = ReviewRun(
        public_id=ReviewRun.build_public_id(),
        assignment=review_run.assignment,
        review_prep=review_run.review_prep,
        status="completed",
        parallelism=1,
    )
    session.add(second_run)
    session.commit()
    session.add_all(
        [
            ReviewResult(
                public_id=ReviewResult.build_public_id(),
                review_run_id=review_run.id,
                submission_id=submission.id,
                total_score=90.0,
                score_scale=100,
                summary="未发布的新评分",
                status="finalized",
            ),
            ReviewResult(
                public_id=ReviewResult.build_public_id(),
                review_run_id=second_run.id,
                submission_id=submission.id,
                total_score=80.0,
                score_scale=100,
                summary="已发布评分",
                status="published",
            ),
        ]
    )
    session.commit()

    payload = CourseService(session).get_review_summary(review_run.assignment.course.public_id)
    first_cell = payload["rows"][0]["results"][0]

    assert first_cell["score"] == 80.0
    assert first_cell["summary"] == "已发布评分"
    assert first_cell["status"] == "published"


def test_review_run_publish_is_idempotent_for_active_task():
    session = build_session()
    review_run, submission, _ = seed_review_context(session)
    session.add(
        ReviewResult(
            public_id=ReviewResult.build_public_id(),
            review_run_id=review_run.id,
            submission_id=submission.id,
            total_score=82.0,
            score_scale=100,
            summary="可发布结果",
            status="finalized",
        )
    )
    session.commit()
    service = ReviewRunService(session)

    first_task = service.publish(review_run_public_id=review_run.public_id)
    second_task = service.publish(review_run_public_id=review_run.public_id)
    task_count = session.query(ApprovalTask).filter(ApprovalTask.object_public_id == review_run.public_id).count()

    assert first_task.public_id == second_task.public_id
    assert task_count == 1


def test_approval_execute_publishes_results_and_cancels_duplicate_publish_tasks():
    session = build_session()
    review_run, submission, _ = seed_review_context(session)
    result = ReviewResult(
        public_id=ReviewResult.build_public_id(),
        review_run_id=review_run.id,
        submission_id=submission.id,
        total_score=82.0,
        score_scale=100,
        summary="可发布结果",
        status="finalized",
    )
    session.add(result)
    session.commit()
    first_task = ReviewRunService(session).publish(review_run_public_id=review_run.public_id)
    duplicate_task = ApprovalTask(
        public_id=ApprovalTask.build_public_id(),
        object_type="review_run",
        object_public_id=review_run.public_id,
        action_type="publish",
        status="pending",
        title="重复发布审批",
        summary="重复任务",
        command_preview_json=[],
    )
    session.add(duplicate_task)
    session.commit()

    approval_service = ApprovalService(session)
    approval_service.approve(approval_task_public_id=first_task.public_id, operator_note=None)
    approval_service.execute_approved_side_effects(approval_task_public_id=first_task.public_id)

    session.refresh(result)
    session.refresh(submission)
    session.refresh(first_task)
    session.refresh(duplicate_task)
    assert result.status == "published"
    assert submission.status == "published"
    assert first_task.status == "executed"
    assert duplicate_task.status == "cancelled"


def test_submission_review_graph_skips_validator_when_disabled(monkeypatch):
    session = build_session()
    review_run, submission, _ = seed_review_context(session)
    graph = SubmissionReviewGraph(session)
    calls: list[str] = []

    monkeypatch.setattr(
        graph.runtime_settings_store,
        "load",
        lambda: RuntimeReviewSettings(
            review_prep_max_answer_rounds=3,
            review_run_enable_validation_agent=False,
            review_run_default_parallelism=4,
        ),
    )

    def fake_run(*, stage_name: str, **kwargs):
        calls.append(stage_name)
        if stage_name != "grading_agent":
            raise AssertionError(f"不应调用额外阶段：{stage_name}")
        return SimpleNamespace(
            output=SimpleNamespace(
                structured_output={
                    "total_score": 92.0,
                    "score_scale": 100,
                    "summary": "答案总体正确",
                    "decision": "accepted",
                    "confidence": 0.88,
                    "item_results": [{"question_no": 1, "score": 92.0, "reason": "正确"}],
                },
                confidence=0.88,
            )
        )

    monkeypatch.setattr(graph.executor, "run", fake_run)

    next_state = graph.grade_submission(
        {
            "review_run_public_id": review_run.public_id,
            "submission_public_id": submission.public_id,
            "operator_id": "tester",
            "selected_assets": [],
            "submission_text": "学生答案",
        }
    )

    assert calls == ["grading_agent"]
    assert next_state["validation_output"]["status"] == "validated"
    assert next_state["validation_output"]["validation_skipped"] is True


def test_submission_review_graph_extracts_text_and_visual_assets_for_docx_like_files(monkeypatch, tmp_path):
    session = build_session()
    review_run, submission, _ = seed_review_context(session)
    graph = SubmissionReviewGraph(session)
    monkeypatch.setattr(graph.settings, "runtime_root", str(tmp_path / "runtime"))
    graph.settings.ensure_runtime_dirs()

    source_file = tmp_path / "sample.docx"
    source_file.write_bytes(b"docx-bytes")
    parse_calls: list[bool] = []

    def fake_parse(path, *, include_ocr=True):
        parse_calls.append(include_ocr)
        return ParsedDocument(
            parser_name="docx",
            text="第8题与第9题的正文提取结果",
            notes=["共识别到 2 张内嵌图片"],
            images_detected=2,
            visual_assets=[
                VisualAsset(origin="word/media/image1.png", mime_type="image/png", data=b"image-1"),
                VisualAsset(origin="word/media/image2.png", mime_type="image/png", data=b"image-2"),
            ],
        )

    monkeypatch.setattr(graph.parser, "parse", fake_parse)

    next_state = graph.parse_assets(
        {
            "review_run_public_id": review_run.public_id,
            "submission_public_id": submission.public_id,
            "operator_id": "tester",
            "selected_assets": [
                {
                    "public_id": "asset_docx_1",
                    "logical_path": "作业1_张三.docx",
                    "real_path": str(source_file),
                    "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }
            ],
        }
    )

    assert parse_calls == [False]
    assert "[提取正文] 作业1_张三.docx" in next_state["submission_text"]
    assert "第8题与第9题的正文提取结果" in next_state["submission_text"]
    assert len(next_state["extracted_visual_assets"]) == 2
    assert all(Path(item["real_path"]).exists() for item in next_state["extracted_visual_assets"])
    assert all(item["logical_path"].startswith("作业1_张三.docx / 内嵌图片") for item in next_state["extracted_visual_assets"])


def test_submission_review_graph_grade_submission_passes_extracted_visual_assets(monkeypatch, tmp_path):
    session = build_session()
    review_run, submission, _ = seed_review_context(session)
    graph = SubmissionReviewGraph(session)
    extracted_image = tmp_path / "embedded.png"
    extracted_image.write_bytes(b"image")
    captured_payloads: list[dict[str, object]] = []

    monkeypatch.setattr(
        graph.runtime_settings_store,
        "load",
        lambda: RuntimeReviewSettings(
            review_prep_max_answer_rounds=3,
            review_run_enable_validation_agent=False,
            review_run_default_parallelism=4,
        ),
    )

    def fake_run(*, stage_name: str, envelope, **kwargs):
        if stage_name == "grading_agent":
            captured_payloads.append(envelope.payload)
            return SimpleNamespace(
                output=SimpleNamespace(
                    structured_output={
                        "total_score": 85.0,
                        "score_scale": 100,
                        "summary": "已结合正文和图片评分",
                        "decision": "accepted",
                        "confidence": 0.9,
                        "item_results": [{"question_no": 1, "score": 85.0, "reason": "基本正确"}],
                    },
                    confidence=0.9,
                )
            )
        raise AssertionError(f"不应调用额外阶段：{stage_name}")

    monkeypatch.setattr(graph.executor, "run", fake_run)

    graph.grade_submission(
        {
            "review_run_public_id": review_run.public_id,
            "submission_public_id": submission.public_id,
            "operator_id": "tester",
            "selected_assets": [
                {
                    "public_id": "asset_docx_1",
                    "logical_path": "作业1_张三.docx",
                    "real_path": str(tmp_path / "sample.docx"),
                    "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }
            ],
            "submission_text": "提取出的正文",
            "extracted_visual_assets": [
                {
                    "logical_path": "作业1_张三.docx / 内嵌图片 1",
                    "real_path": str(extracted_image),
                    "mime_type": "image/png",
                    "size_bytes": 5,
                }
            ],
        }
    )

    assert len(captured_payloads) == 1
    assert captured_payloads[0]["submission_text"] == "提取出的正文"
    assert captured_payloads[0]["extracted_visual_assets"] == [
        {
            "logical_path": "作业1_张三.docx / 内嵌图片 1",
            "real_path": str(extracted_image),
            "mime_type": "image/png",
            "size_bytes": 5,
        }
    ]
