from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.submissions import (
    SubmissionImportBatchCreate,
    SubmissionImportBatchRead,
    SubmissionImportConfirmRequest,
    SubmissionRead,
)
from backend.services.serializers import submission_import_batch_read, submission_read
from backend.services.submissions import SubmissionService


router = APIRouter(tags=["submissions"])


@router.post("/assignments/{assignment_public_id}/submission-imports", response_model=SubmissionImportBatchRead)
def create_submission_import(
    assignment_public_id: str,
    payload: SubmissionImportBatchCreate,
    session: Session = Depends(get_db),
) -> SubmissionImportBatchRead:
    service = SubmissionService(session)
    batch = service.create_import_batch(assignment_public_id=assignment_public_id, root_path=payload.root_path)
    return submission_import_batch_read(batch)


@router.post("/submission-imports/{batch_public_id}/run", response_model=SubmissionImportBatchRead)
def run_submission_import(batch_public_id: str, session: Session = Depends(get_db)) -> SubmissionImportBatchRead:
    service = SubmissionService(session)
    return submission_import_batch_read(service.run_import_batch(batch_public_id=batch_public_id))


@router.post("/submission-imports/{batch_public_id}/cancel", response_model=SubmissionImportBatchRead)
def cancel_submission_import(batch_public_id: str, session: Session = Depends(get_db)) -> SubmissionImportBatchRead:
    service = SubmissionService(session)
    return submission_import_batch_read(service.cancel_import_batch(batch_public_id=batch_public_id))


@router.get("/submission-imports/{batch_public_id}", response_model=SubmissionImportBatchRead)
def get_submission_import(batch_public_id: str, session: Session = Depends(get_db)) -> SubmissionImportBatchRead:
    service = SubmissionService(session)
    return submission_import_batch_read(service.get_import_batch(batch_public_id))


@router.get("/submission-imports/{batch_public_id}/submissions", response_model=list[SubmissionRead])
def list_batch_submissions(batch_public_id: str, session: Session = Depends(get_db)) -> list[SubmissionRead]:
    service = SubmissionService(session)
    return [submission_read(item) for item in service.list_batch_submissions(batch_public_id)]


@router.post("/submission-imports/{batch_public_id}/confirm", response_model=SubmissionImportBatchRead)
def confirm_submission_import(
    batch_public_id: str,
    payload: SubmissionImportConfirmRequest,
    session: Session = Depends(get_db),
) -> SubmissionImportBatchRead:
    service = SubmissionService(session)
    batch = service.confirm_import_batch(batch_public_id=batch_public_id, items=[item.model_dump() for item in payload.items])
    return submission_import_batch_read(batch)


@router.post("/submission-imports/{batch_public_id}/apply", response_model=SubmissionImportBatchRead)
def apply_submission_import(batch_public_id: str, session: Session = Depends(get_db)) -> SubmissionImportBatchRead:
    service = SubmissionService(session)
    return submission_import_batch_read(service.apply_import_batch(batch_public_id=batch_public_id))


@router.get("/assignments/{assignment_public_id}/submissions", response_model=list[SubmissionRead])
def list_assignment_submissions(assignment_public_id: str, session: Session = Depends(get_db)) -> list[SubmissionRead]:
    service = SubmissionService(session)
    return [submission_read(item) for item in service.list_assignment_submissions(assignment_public_id)]
