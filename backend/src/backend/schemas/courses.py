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
