from __future__ import annotations

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.background_jobs import BackgroundJobCancelled, get_background_job_registry
from backend.core.errors import DomainError
from backend.db.session import SessionLocal
from backend.db.repositories import CourseRepository, EnrollmentRepository, RosterRepository
from backend.domain.models import Course, RosterCandidateRow, RosterImportBatch
from backend.domain.state_machine import ensure_transition
from backend.graphs.course_init_graph import CourseInitGraph
from backend.infra.observability import AuditService
from backend.infra.storage import save_upload


class RosterService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.course_repo = CourseRepository(session)
        self.roster_repo = RosterRepository(session)
        self.enrollment_repo = EnrollmentRepository(session)
        self.audit_service = AuditService(session)
        self.job_registry = get_background_job_registry()

    async def create_batch(self, *, course_public_id: str, files: list[UploadFile], parse_mode: str) -> object:
        course = self.course_repo.get_by_public_id(course_public_id)
        stored_files = [await save_upload(file, "rosters") for file in files]
        batch = self.roster_repo.create_batch(
            course,
            source_files_json=[
                {
                    "original_name": item.original_name,
                    "stored_name": item.stored_name,
                    "path": item.path,
                    "size_bytes": item.size_bytes,
                }
                for item in stored_files
            ],
            parse_mode=parse_mode,
        )
        self.audit_service.record(
            event_type="roster_import_uploaded",
            object_type="roster_import_batch",
            object_public_id=batch.public_id,
            payload={"file_count": len(stored_files)},
        )
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def run_batch(self, *, batch_public_id: str, operator_id: str = "system"):
        batch = self.roster_repo.get_batch(batch_public_id)
        if self.job_registry.is_active("roster_import_batch", batch.public_id):
            raise DomainError("名单初始化 Agent 已在运行中。", code="roster_job_running", status_code=409)
        batch.course.status = "initializing"
        batch.status = "queued"
        batch.error_message = None
        self.audit_service.record(
            event_type="roster_import_run_requested",
            object_type="roster_import_batch",
            object_public_id=batch.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        self.session.refresh(batch)
        self.job_registry.start(
            object_type="roster_import_batch",
            object_public_id=batch.public_id,
            label="名单初始化 Agent",
            target=lambda: self._run_batch_in_background(batch.public_id, operator_id),
        )
        return batch

    def cancel_batch(self, *, batch_public_id: str, operator_id: str = "system"):
        batch = self.roster_repo.get_batch(batch_public_id)
        if not self.job_registry.request_cancel("roster_import_batch", batch.public_id):
            raise DomainError("当前没有可停止的名单初始化任务。", code="roster_job_not_running", status_code=409)
        self.audit_service.record(
            event_type="roster_import_cancel_requested",
            object_type="roster_import_batch",
            object_public_id=batch.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def get_batch(self, batch_public_id: str):
        return self.roster_repo.get_batch(batch_public_id)

    def list_candidates(self, batch_public_id: str) -> list[RosterCandidateRow]:
        batch = self.roster_repo.get_batch(batch_public_id)
        return self.roster_repo.list_candidates(batch)

    def confirm_batch(self, *, batch_public_id: str, decisions: list[dict], operator_id: str = "system"):
        batch = self.roster_repo.get_batch(batch_public_id)
        candidates_by_public_id = {candidate.public_id: candidate for candidate in self.roster_repo.list_candidates(batch)}
        for item in decisions:
            candidate = candidates_by_public_id[item["candidate_public_id"]]
            candidate.decision_status = item["decision_status"]
            if item.get("student_no") is not None:
                candidate.student_no = item["student_no"]
            if item.get("name"):
                candidate.name = item["name"]
            candidate.decision_note = item.get("decision_note")
        ensure_transition("roster_import_batch", batch.status, "confirmed")
        batch.status = "confirmed"
        self.audit_service.record(
            event_type="roster_import_confirmed",
            object_type="roster_import_batch",
            object_public_id=batch.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def apply_batch(self, *, batch_public_id: str, operator_id: str = "system"):
        batch = self.roster_repo.get_batch(batch_public_id)
        course = batch.course
        candidates = self.roster_repo.list_candidates(batch)
        self.enrollment_repo.apply_roster(course, batch, candidates)
        ensure_transition("roster_import_batch", batch.status, "applied")
        batch.status = "applied"
        course.active_roster_batch_id = batch.id
        course.status = "active"
        self.audit_service.record(
            event_type="roster_import_applied",
            object_type="course",
            object_public_id=course.public_id,
            actor_type="user",
            actor_id=operator_id,
            payload={"batch_public_id": batch.public_id},
        )
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def _run_batch_in_background(self, batch_public_id: str, operator_id: str) -> None:
        session = SessionLocal()
        try:
            service = RosterService(session)
            service._execute_batch(batch_public_id=batch_public_id, operator_id=operator_id)
        finally:
            session.close()

    def _execute_batch(self, *, batch_public_id: str, operator_id: str) -> None:
        batch = self.roster_repo.get_batch(batch_public_id)
        try:
            graph = CourseInitGraph(self.session)
            graph.invoke(course_public_id=batch.course.public_id, batch_public_id=batch.public_id, operator_id=operator_id)
            self.session.commit()
        except BackgroundJobCancelled:
            self.session.rollback()
            self._mark_batch_cancelled(batch_public_id=batch_public_id, operator_id=operator_id)
        except Exception as exc:
            self.session.rollback()
            self._mark_batch_failed(
                batch_public_id=batch_public_id,
                operator_id=operator_id,
                error_message=str(exc),
            )

    def _mark_batch_cancelled(self, *, batch_public_id: str, operator_id: str) -> None:
        batch = self.session.scalar(select(RosterImportBatch).where(RosterImportBatch.public_id == batch_public_id))
        if batch is None:
            return
        course = self.session.scalar(select(Course).where(Course.id == batch.course_id))
        batch.status = "cancelled"
        batch.error_message = "已停止名单初始化任务。"
        if course is not None and course.status == "initializing":
            course.status = "active" if course.active_roster_batch_id is not None else "draft"
            course.last_error = None
        self.audit_service.record(
            event_type="roster_import_cancelled",
            object_type="roster_import_batch",
            object_public_id=batch.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()

    def _mark_batch_failed(self, *, batch_public_id: str, operator_id: str, error_message: str) -> None:
        batch = self.session.scalar(select(RosterImportBatch).where(RosterImportBatch.public_id == batch_public_id))
        if batch is None:
            return
        course = self.session.scalar(select(Course).where(Course.id == batch.course_id))
        batch.status = "failed"
        batch.error_message = error_message
        if course is not None:
            course.status = "failed"
            course.last_error = error_message
        self.audit_service.record(
            event_type="roster_import_failed",
            object_type="roster_import_batch",
            object_public_id=batch.public_id,
            actor_type="user",
            actor_id=operator_id,
            payload={"error_message": error_message},
        )
        self.session.commit()
