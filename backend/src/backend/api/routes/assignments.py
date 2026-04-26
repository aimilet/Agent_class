from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.assignments import AssignmentCreate, AssignmentRead
from backend.services.assignments import AssignmentService
from backend.services.serializers import assignment_read


router = APIRouter(tags=["assignments"])


@router.post("/courses/{course_public_id}/assignments", response_model=AssignmentRead)
def create_assignment(
    course_public_id: str,
    payload: AssignmentCreate,
    session: Session = Depends(get_db),
) -> AssignmentRead:
    service = AssignmentService(session)
    assignment = service.create_assignment(course_public_id=course_public_id, **payload.model_dump())
    return assignment_read(assignment)


@router.get("/courses/{course_public_id}/assignments", response_model=list[AssignmentRead])
def list_assignments(course_public_id: str, session: Session = Depends(get_db)) -> list[AssignmentRead]:
    service = AssignmentService(session)
    return [assignment_read(item) for item in service.list_assignments(course_public_id)]
