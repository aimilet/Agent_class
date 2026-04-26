from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.core.errors import DomainError
from backend.domain.models import (
    Assignment,
    Course,
    CourseEnrollment,
    Submission,
    SubmissionAsset,
    SubmissionImportBatch,
    SubmissionMatchCandidate,
)


class AssignmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        course: Course,
        seq_no: int,
        title: str,
        slug: str,
        description: str | None,
        due_at,
    ) -> Assignment:
        existing = self.session.scalar(
            select(Assignment).where(Assignment.course_id == course.id, Assignment.seq_no == seq_no)
        )
        if existing is not None:
            raise DomainError("作业序号已存在。", code="assignment_exists", status_code=409)
        assignment = Assignment(
            public_id=Assignment.build_public_id(),
            course_id=course.id,
            seq_no=seq_no,
            title=title,
            slug=slug,
            description=description,
            due_at=due_at,
            status="draft",
        )
        self.session.add(assignment)
        self.session.flush()
        return assignment

    def get_by_public_id(self, assignment_public_id: str) -> Assignment:
        assignment = self.session.scalar(select(Assignment).where(Assignment.public_id == assignment_public_id))
        if assignment is None:
            raise DomainError("作业不存在。", code="assignment_not_found", status_code=404)
        return assignment

    def list_by_course(self, course: Course) -> list[Assignment]:
        return list(
            self.session.scalars(
                select(Assignment)
                .where(Assignment.course_id == course.id)
                .order_by(Assignment.seq_no.asc())
            ).all()
        )


class SubmissionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_import_batch(self, assignment: Assignment, *, root_path: str) -> SubmissionImportBatch:
        batch = SubmissionImportBatch(
            public_id=SubmissionImportBatch.build_public_id(),
            assignment_id=assignment.id,
            root_path=root_path,
            status="created",
        )
        self.session.add(batch)
        self.session.flush()
        return batch

    def get_import_batch(self, batch_public_id: str) -> SubmissionImportBatch:
        batch = self.session.scalar(select(SubmissionImportBatch).where(SubmissionImportBatch.public_id == batch_public_id))
        if batch is None:
            raise DomainError("作业导入批次不存在。", code="submission_import_batch_not_found", status_code=404)
        return batch

    def list_import_batches_by_assignment(self, assignment: Assignment) -> list[SubmissionImportBatch]:
        return list(
            self.session.scalars(
                select(SubmissionImportBatch)
                .where(SubmissionImportBatch.assignment_id == assignment.id)
                .order_by(SubmissionImportBatch.created_at.desc())
            ).all()
        )

    def list_submissions_by_assignment(self, assignment: Assignment) -> list[Submission]:
        return list(
            self.session.scalars(
                select(Submission)
                .options(selectinload(Submission.assets), selectinload(Submission.match_candidates))
                .where(Submission.assignment_id == assignment.id)
                .order_by(Submission.created_at.asc())
            ).all()
        )

    def list_submissions_by_batch(self, batch: SubmissionImportBatch) -> list[Submission]:
        return list(
            self.session.scalars(
                select(Submission)
                .options(selectinload(Submission.assets), selectinload(Submission.match_candidates))
                .where(Submission.import_batch_id == batch.id)
                .order_by(Submission.created_at.asc())
            ).all()
        )

    def get_submission(self, submission_public_id: str) -> Submission:
        submission = self.session.scalar(
            select(Submission)
            .options(selectinload(Submission.assets), selectinload(Submission.match_candidates))
            .where(Submission.public_id == submission_public_id)
        )
        if submission is None:
            raise DomainError("提交不存在。", code="submission_not_found", status_code=404)
        return submission

    def replace_submissions(self, batch: SubmissionImportBatch, items: list[dict]) -> list[Submission]:
        for submission in self.list_submissions_by_batch(batch):
            self.session.delete(submission)
        created: list[Submission] = []
        for item in items:
            submission = Submission(
                public_id=Submission.build_public_id(),
                assignment_id=batch.assignment_id,
                import_batch_id=batch.id,
                enrollment_id=item.get("enrollment_id"),
                source_entry_name=item["source_entry_name"],
                source_entry_path=item["source_entry_path"],
                matched_by=item.get("matched_by"),
                match_confidence=item.get("match_confidence"),
                match_reason=item.get("match_reason"),
                status=item.get("status", "discovered"),
                canonical_name=item.get("canonical_name"),
                current_path=item.get("current_path", item["source_entry_path"]),
            )
            self.session.add(submission)
            self.session.flush()
            for asset in item.get("assets", []):
                self.session.add(
                    SubmissionAsset(
                        public_id=SubmissionAsset.build_public_id(),
                        submission_id=submission.id,
                        logical_path=asset["logical_path"],
                        real_path=asset["real_path"],
                        file_hash=asset.get("file_hash"),
                        mime_type=asset.get("mime_type"),
                        size_bytes=asset.get("size_bytes", 0),
                        asset_role=asset.get("asset_role"),
                        selected_by_agent=asset.get("selected_by_agent", False),
                        selected_reason=asset.get("selected_reason"),
                        is_ignored=asset.get("is_ignored", False),
                    )
                )
            for candidate in item.get("match_candidates", []):
                self.session.add(
                    SubmissionMatchCandidate(
                        public_id=SubmissionMatchCandidate.build_public_id(),
                        submission_id=submission.id,
                        enrollment_id=candidate["enrollment_id"],
                        confidence=candidate["confidence"],
                        reason=candidate.get("reason"),
                        rank_order=candidate.get("rank_order", 1),
                    )
                )
            created.append(submission)
        self.session.flush()
        return created

    def bind_submission(self, submission: Submission, enrollment: CourseEnrollment | None, *, status: str | None = None) -> Submission:
        submission.enrollment_id = enrollment.id if enrollment is not None else None
        if status is not None:
            submission.status = status
        self.session.flush()
        return submission
