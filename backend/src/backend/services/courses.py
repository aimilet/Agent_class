from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.repositories import CourseRepository, EnrollmentRepository
from backend.infra.observability import AuditService


class CourseService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.course_repo = CourseRepository(session)
        self.enrollment_repo = EnrollmentRepository(session)
        self.audit_service = AuditService(session)

    def create_course(self, *, course_code: str, course_name: str, term: str, class_label: str, teacher_name: str | None):
        course = self.course_repo.create(
            course_code=course_code,
            course_name=course_name,
            term=term,
            class_label=class_label,
            teacher_name=teacher_name,
        )
        self.audit_service.record(
            event_type="course_created",
            object_type="course",
            object_public_id=course.public_id,
            payload={"course_code": course.course_code, "term": course.term},
        )
        self.session.commit()
        self.session.refresh(course)
        return course

    def list_courses(self):
        return self.course_repo.list_all()

    def get_course(self, course_public_id: str):
        return self.course_repo.get_by_public_id(course_public_id)

    def list_enrollments(self, course_public_id: str):
        course = self.course_repo.get_by_public_id(course_public_id)
        return self.enrollment_repo.list_by_course(course)
