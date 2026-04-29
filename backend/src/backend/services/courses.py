from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from backend.db.repositories import CourseRepository, EnrollmentRepository
from backend.domain.models import Assignment, Course, ReviewResult, ReviewRun, Submission
from backend.infra.observability import AuditService


SUMMARY_RESULT_STATUS_PRIORITY = {
    "validated": 1,
    "finalized": 2,
    "published": 3,
}


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

    def get_review_summary(self, course_public_id: str) -> dict:
        course = self.session.scalar(
            select(Course)
            .options(
                selectinload(Course.enrollments),
                selectinload(Course.assignments),
                selectinload(Course.assignments)
                .selectinload(Assignment.review_runs)
                .selectinload(ReviewRun.results)
                .selectinload(ReviewResult.submission)
                .selectinload(Submission.enrollment),
            )
            .where(Course.public_id == course_public_id)
        )
        if course is None:
            course = self.course_repo.get_by_public_id(course_public_id)

        assignments = sorted(course.assignments, key=lambda item: item.seq_no)
        latest_result_by_key: dict[tuple[int, int], ReviewResult] = {}
        for assignment in assignments:
            for review_run in assignment.review_runs:
                for result in review_run.results:
                    if result.status not in SUMMARY_RESULT_STATUS_PRIORITY:
                        continue
                    enrollment = result.submission.enrollment
                    if enrollment is None:
                        continue
                    key = (assignment.id, enrollment.id)
                    existing = latest_result_by_key.get(key)
                    if existing is None or self._is_better_summary_result(result, existing):
                        latest_result_by_key[key] = result

        rows: list[dict] = []
        enrollments = sorted(
            course.enrollments,
            key=lambda item: (
                item.display_student_no or "ZZZZZZZZ",
                item.display_name,
                item.public_id,
            ),
        )
        for enrollment in enrollments:
            cells: list[dict] = []
            for assignment in assignments:
                result = latest_result_by_key.get((assignment.id, enrollment.id))
                cells.append(
                    {
                        "assignment_public_id": assignment.public_id,
                        "review_result_public_id": result.public_id if result is not None else None,
                        "submission_public_id": result.submission.public_id if result is not None else None,
                        "score": result.total_score if result is not None else None,
                        "summary": result.summary if result is not None else None,
                        "status": result.status if result is not None else None,
                    }
                )
            rows.append(
                {
                    "enrollment_public_id": enrollment.public_id,
                    "student_no": enrollment.display_student_no,
                    "student_name": enrollment.display_name,
                    "results": cells,
                }
            )

        return {
            "course_public_id": course.public_id,
            "assignments": [
                {
                    "assignment_public_id": assignment.public_id,
                    "seq_no": assignment.seq_no,
                    "title": assignment.title,
                }
                for assignment in assignments
            ],
            "rows": rows,
        }

    def _is_better_summary_result(self, candidate: ReviewResult, existing: ReviewResult) -> bool:
        candidate_priority = SUMMARY_RESULT_STATUS_PRIORITY.get(candidate.status, 0)
        existing_priority = SUMMARY_RESULT_STATUS_PRIORITY.get(existing.status, 0)
        if candidate_priority != existing_priority:
            return candidate_priority > existing_priority
        return (candidate.published_at or candidate.updated_at) > (existing.published_at or existing.updated_at)
