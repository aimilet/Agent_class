from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.background_jobs import BackgroundJobCancelled, get_background_job_registry
from backend.core.errors import DomainError
from backend.core.pathing import normalize_user_path
from backend.db.session import SessionLocal
from backend.db.repositories import AssignmentRepository, EnrollmentRepository, SubmissionRepository
from backend.domain.models import SubmissionImportBatch
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
        self.job_registry = get_background_job_registry()

    def create_import_batch(self, *, assignment_public_id: str, root_path: str):
        assignment = self.assignment_repo.get_by_public_id(assignment_public_id)
        normalized_root_path = normalize_user_path(root_path)
        batch = self.submission_repo.create_import_batch(assignment, root_path=normalized_root_path)
        self.audit_service.record(
            event_type="submission_import_created",
            object_type="submission_import_batch",
            object_public_id=batch.public_id,
            payload={
                "assignment_public_id": assignment.public_id,
                "root_path": root_path,
                "normalized_root_path": normalized_root_path,
            },
        )
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def run_import_batch(self, *, batch_public_id: str, operator_id: str = "system"):
        batch = self.submission_repo.get_import_batch(batch_public_id)
        if self.job_registry.is_active("submission_import_batch", batch.public_id):
            raise DomainError("作业导入 Agent 已在运行中。", code="submission_job_running", status_code=409)
        normalized_root_path = normalize_user_path(batch.root_path)
        if normalized_root_path != batch.root_path:
            batch.root_path = normalized_root_path
        batch.status = "scanning"
        batch.error_message = None
        self.audit_service.record(
            event_type="submission_import_run_requested",
            object_type="submission_import_batch",
            object_public_id=batch.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        self.session.refresh(batch)
        self.job_registry.start(
            object_type="submission_import_batch",
            object_public_id=batch.public_id,
            label="作业导入 Agent",
            target=lambda: self._run_import_batch_in_background(batch.public_id, operator_id),
        )
        return batch

    def cancel_import_batch(self, *, batch_public_id: str, operator_id: str = "system"):
        batch = self.submission_repo.get_import_batch(batch_public_id)
        if not self.job_registry.request_cancel("submission_import_batch", batch.public_id):
            raise DomainError("当前没有可停止的作业导入任务。", code="submission_job_not_running", status_code=409)
        self.audit_service.record(
            event_type="submission_import_cancel_requested",
            object_type="submission_import_batch",
            object_public_id=batch.public_id,
            actor_type="user",
            actor_id=operator_id,
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

    def _run_import_batch_in_background(self, batch_public_id: str, operator_id: str) -> None:
        session = SessionLocal()
        try:
            service = SubmissionService(session)
            service._execute_import_batch(batch_public_id=batch_public_id, operator_id=operator_id)
        finally:
            session.close()

    def _execute_import_batch(self, *, batch_public_id: str, operator_id: str) -> None:
        batch = self.submission_repo.get_import_batch(batch_public_id)
        try:
            graph = SubmissionImportGraph(self.session)
            graph.invoke(
                assignment_public_id=batch.assignment.public_id,
                batch_public_id=batch.public_id,
                operator_id=operator_id,
            )
            self.session.commit()
        except BackgroundJobCancelled:
            self.session.rollback()
            self._mark_import_batch_cancelled(batch_public_id=batch_public_id, operator_id=operator_id)
        except Exception as exc:
            self.session.rollback()
            self._mark_import_batch_failed(
                batch_public_id=batch_public_id,
                operator_id=operator_id,
                error_message=str(exc),
            )

    def _mark_import_batch_cancelled(self, *, batch_public_id: str, operator_id: str) -> None:
        batch = self.session.scalar(select(SubmissionImportBatch).where(SubmissionImportBatch.public_id == batch_public_id))
        if batch is None:
            return
        batch.status = "cancelled"
        batch.error_message = "已停止作业导入任务。"
        self.audit_service.record(
            event_type="submission_import_cancelled",
            object_type="submission_import_batch",
            object_public_id=batch.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()

    def _mark_import_batch_failed(self, *, batch_public_id: str, operator_id: str, error_message: str) -> None:
        batch = self.session.scalar(select(SubmissionImportBatch).where(SubmissionImportBatch.public_id == batch_public_id))
        if batch is None:
            return
        batch.status = "failed"
        batch.error_message = error_message
        self.audit_service.record(
            event_type="submission_import_failed",
            object_type="submission_import_batch",
            object_public_id=batch.public_id,
            actor_type="user",
            actor_id=operator_id,
            payload={"error_message": error_message},
        )
        self.session.commit()
