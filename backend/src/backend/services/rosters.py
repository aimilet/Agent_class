from __future__ import annotations

from fastapi import UploadFile
from sqlalchemy.orm import Session

from backend.db.repositories import CourseRepository, EnrollmentRepository, RosterRepository
from backend.domain.models import RosterCandidateRow
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
        graph = CourseInitGraph(self.session)
        graph.invoke(course_public_id=batch.course.public_id, batch_public_id=batch.public_id, operator_id=operator_id)
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
