from __future__ import annotations

from pydantic import BaseModel

from backend.schemas.common import TimestampedPublicRead


class CourseCreate(BaseModel):
    course_code: str
    course_name: str
    term: str
    class_label: str = ""
    teacher_name: str | None = None


class CourseRead(TimestampedPublicRead):
    course_code: str
    course_name: str
    term: str
    class_label: str
    teacher_name: str | None
    status: str
    active_roster_batch_id: str | None = None
    last_error: str | None = None


class CourseEnrollmentRead(TimestampedPublicRead):
    course_public_id: str
    person_public_id: str
    display_student_no: str | None
    display_name: str
    status: str


class CourseReviewSummaryAssignmentRead(BaseModel):
    assignment_public_id: str
    seq_no: int
    title: str


class CourseReviewSummaryCellRead(BaseModel):
    assignment_public_id: str
    review_result_public_id: str | None = None
    submission_public_id: str | None = None
    score: float | None = None
    summary: str | None = None
    status: str | None = None


class CourseReviewSummaryRowRead(BaseModel):
    enrollment_public_id: str
    student_no: str | None = None
    student_name: str
    results: list[CourseReviewSummaryCellRead]


class CourseReviewSummaryRead(BaseModel):
    course_public_id: str
    assignments: list[CourseReviewSummaryAssignmentRead]
    rows: list[CourseReviewSummaryRowRead]
