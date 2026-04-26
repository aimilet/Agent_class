from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.repositories import AssignmentRepository, CourseRepository
from backend.infra.observability import AuditService
from backend.services.helpers import slugify


class AssignmentService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.course_repo = CourseRepository(session)
        self.assignment_repo = AssignmentRepository(session)
        self.audit_service = AuditService(session)

    def create_assignment(self, *, course_public_id: str, seq_no: int, title: str, description: str | None, due_at):
        course = self.course_repo.get_by_public_id(course_public_id)
        assignment = self.assignment_repo.create(
            course=course,
            seq_no=seq_no,
            title=title,
            slug=slugify(title),
            description=description,
            due_at=due_at,
        )
        assignment.status = "accepting_submissions"
        self.audit_service.record(
            event_type="assignment_created",
            object_type="assignment",
            object_public_id=assignment.public_id,
            payload={"course_public_id": course.public_id, "seq_no": assignment.seq_no},
        )
        self.session.commit()
        self.session.refresh(assignment)
        return assignment

    def list_assignments(self, course_public_id: str):
        course = self.course_repo.get_by_public_id(course_public_id)
        return self.assignment_repo.list_by_course(course)

    def get_assignment(self, assignment_public_id: str):
        return self.assignment_repo.get_by_public_id(assignment_public_id)
