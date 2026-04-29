from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.courses import CourseCreate, CourseEnrollmentRead, CourseRead, CourseReviewSummaryRead
from backend.services.courses import CourseService
from backend.services.serializers import course_read, course_review_summary_read, enrollment_read


router = APIRouter(tags=["courses"])


@router.post("/courses", response_model=CourseRead)
def create_course(payload: CourseCreate, session: Session = Depends(get_db)) -> CourseRead:
    service = CourseService(session)
    course = service.create_course(**payload.model_dump())
    return course_read(course)


@router.get("/courses", response_model=list[CourseRead])
def list_courses(session: Session = Depends(get_db)) -> list[CourseRead]:
    service = CourseService(session)
    return [course_read(item) for item in service.list_courses()]


@router.get("/courses/{course_public_id}", response_model=CourseRead)
def get_course(course_public_id: str, session: Session = Depends(get_db)) -> CourseRead:
    service = CourseService(session)
    return course_read(service.get_course(course_public_id))


@router.get("/courses/{course_public_id}/enrollments", response_model=list[CourseEnrollmentRead])
def list_enrollments(course_public_id: str, session: Session = Depends(get_db)) -> list[CourseEnrollmentRead]:
    service = CourseService(session)
    return [enrollment_read(item) for item in service.list_enrollments(course_public_id)]


@router.get("/courses/{course_public_id}/review-summary", response_model=CourseReviewSummaryRead)
def get_review_summary(course_public_id: str, session: Session = Depends(get_db)) -> CourseReviewSummaryRead:
    service = CourseService(session)
    return course_review_summary_read(service.get_review_summary(course_public_id))
