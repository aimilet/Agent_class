from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.repositories import AssignmentRepository, EnrollmentRepository, SubmissionRepository
from backend.domain.state_machine import ensure_transition
from backend.graphs.submission_import_graph import SubmissionImportGraph
from backend.infra.observability import AuditService


class SubmissionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.assignment_repo = AssignmentRepository(session)
        self.enrollment_repo = EnrollmentRepository(session)
        self.submission_repo = SubmissionRepository(session)
        self.audit_service = AuditService(session)

    def create_import_batch(self, *, assignment_public_id: str, root_path: str):
        assignment = self.assignment_repo.get_by_public_id(assignment_public_id)
        batch = self.submission_repo.create_import_batch(assignment, root_path=root_path)
        self.audit_service.record(
            event_type="submission_import_created",
            object_type="submission_import_batch",
            object_public_id=batch.public_id,
            payload={"assignment_public_id": assignment.public_id, "root_path": root_path},
        )
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def run_import_batch(self, *, batch_public_id: str, operator_id: str = "system"):
        batch = self.submission_repo.get_import_batch(batch_public_id)
        graph = SubmissionImportGraph(self.session)
        graph.invoke(
            assignment_public_id=batch.assignment.public_id,
            batch_public_id=batch.public_id,
            operator_id=operator_id,
        )
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def get_import_batch(self, batch_public_id: str):
        return self.submission_repo.get_import_batch(batch_public_id)

    def list_batch_submissions(self, batch_public_id: str):
        batch = self.submission_repo.get_import_batch(batch_public_id)
        return self.submission_repo.list_submissions_by_batch(batch)

    def confirm_import_batch(self, *, batch_public_id: str, items: list[dict], operator_id: str = "system"):
        batch = self.submission_repo.get_import_batch(batch_public_id)
        for item in items:
            submission = self.submission_repo.get_submission(item["submission_public_id"])
            enrollment = self.enrollment_repo.get_by_public_id(item["enrollment_public_id"]) if item.get("enrollment_public_id") else None
            status = item.get("status") or ("confirmed" if enrollment is not None else "unmatched")
            self.submission_repo.bind_submission(submission, enrollment, status=status)
        ensure_transition("submission_import_batch", batch.status, "confirmed")
        batch.status = "confirmed"
        self.audit_service.record(
            event_type="submission_import_confirmed",
            object_type="submission_import_batch",
            object_public_id=batch.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def apply_import_batch(self, *, batch_public_id: str, operator_id: str = "system"):
        batch = self.submission_repo.get_import_batch(batch_public_id)
        submissions = self.submission_repo.list_submissions_by_batch(batch)
        for submission in submissions:
            if submission.enrollment_id is not None:
                submission.status = "naming_pending"
        ensure_transition("submission_import_batch", batch.status, "applied")
        batch.status = "applied"
        batch.assignment.status = "naming_ready"
        self.audit_service.record(
            event_type="submission_import_applied",
            object_type="assignment",
            object_public_id=batch.assignment.public_id,
            actor_type="user",
            actor_id=operator_id,
            payload={"batch_public_id": batch.public_id},
        )
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def list_assignment_submissions(self, assignment_public_id: str):
        assignment = self.assignment_repo.get_by_public_id(assignment_public_id)
        return self.submission_repo.list_submissions_by_assignment(assignment)
