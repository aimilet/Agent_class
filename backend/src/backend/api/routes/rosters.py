from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.rosters import RosterCandidateRead, RosterImportBatchRead, RosterImportConfirmRequest
from backend.services.rosters import RosterService
from backend.services.serializers import roster_batch_read, roster_candidate_read


router = APIRouter(tags=["rosters"])


@router.post("/courses/{course_public_id}/roster-imports", response_model=RosterImportBatchRead)
async def create_roster_import(
    course_public_id: str,
    files: list[UploadFile] = File(...),
    parse_mode: str = Form(default="auto"),
    session: Session = Depends(get_db),
) -> RosterImportBatchRead:
    service = RosterService(session)
    batch = await service.create_batch(course_public_id=course_public_id, files=files, parse_mode=parse_mode)
    return roster_batch_read(batch)


@router.post("/roster-imports/{batch_public_id}/run", response_model=RosterImportBatchRead)
def run_roster_import(batch_public_id: str, session: Session = Depends(get_db)) -> RosterImportBatchRead:
    service = RosterService(session)
    return roster_batch_read(service.run_batch(batch_public_id=batch_public_id))


@router.post("/roster-imports/{batch_public_id}/cancel", response_model=RosterImportBatchRead)
def cancel_roster_import(batch_public_id: str, session: Session = Depends(get_db)) -> RosterImportBatchRead:
    service = RosterService(session)
    return roster_batch_read(service.cancel_batch(batch_public_id=batch_public_id))


@router.get("/roster-imports/{batch_public_id}", response_model=RosterImportBatchRead)
def get_roster_import(batch_public_id: str, session: Session = Depends(get_db)) -> RosterImportBatchRead:
    service = RosterService(session)
    return roster_batch_read(service.get_batch(batch_public_id))


@router.get("/roster-imports/{batch_public_id}/candidates", response_model=list[RosterCandidateRead])
def list_roster_candidates(batch_public_id: str, session: Session = Depends(get_db)) -> list[RosterCandidateRead]:
    service = RosterService(session)
    return [roster_candidate_read(item) for item in service.list_candidates(batch_public_id)]


@router.post("/roster-imports/{batch_public_id}/confirm", response_model=RosterImportBatchRead)
def confirm_roster_import(
    batch_public_id: str,
    payload: RosterImportConfirmRequest,
    session: Session = Depends(get_db),
) -> RosterImportBatchRead:
    service = RosterService(session)
    batch = service.confirm_batch(batch_public_id=batch_public_id, decisions=[item.model_dump() for item in payload.items])
    return roster_batch_read(batch)


@router.post("/roster-imports/{batch_public_id}/apply", response_model=RosterImportBatchRead)
def apply_roster_import(batch_public_id: str, session: Session = Depends(get_db)) -> RosterImportBatchRead:
    service = RosterService(session)
    return roster_batch_read(service.apply_batch(batch_public_id=batch_public_id))
