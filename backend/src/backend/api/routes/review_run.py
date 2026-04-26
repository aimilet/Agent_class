from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.approvals import ApprovalTaskRead
from backend.schemas.review_run import ManualReviewUpdate, ReviewResultRead, ReviewRunCreate, ReviewRunRead
from backend.services.review_run import ReviewRunService
from backend.services.serializers import approval_task_read, review_result_read, review_run_read


router = APIRouter(tags=["review-run"])


@router.post("/assignments/{assignment_public_id}/review-runs", response_model=ReviewRunRead)
def create_review_run(
    assignment_public_id: str,
    payload: ReviewRunCreate,
    session: Session = Depends(get_db),
) -> ReviewRunRead:
    service = ReviewRunService(session)
    review_run = service.create_review_run(assignment_public_id=assignment_public_id, **payload.model_dump())
    return review_run_read(review_run)


@router.post("/review-runs/{review_run_public_id}/start", response_model=ReviewRunRead)
def start_review_run(review_run_public_id: str, session: Session = Depends(get_db)) -> ReviewRunRead:
    service = ReviewRunService(session)
    return review_run_read(service.start_review_run(review_run_public_id=review_run_public_id))


@router.get("/review-runs/{review_run_public_id}", response_model=ReviewRunRead)
def get_review_run(review_run_public_id: str, session: Session = Depends(get_db)) -> ReviewRunRead:
    service = ReviewRunService(session)
    return review_run_read(service.get_review_run(review_run_public_id))


@router.get("/review-runs/{review_run_public_id}/results", response_model=list[ReviewResultRead])
def list_review_results(review_run_public_id: str, session: Session = Depends(get_db)) -> list[ReviewResultRead]:
    service = ReviewRunService(session)
    return [review_result_read(item) for item in service.list_results(review_run_public_id)]


@router.patch("/review-results/{review_result_public_id}/manual-review", response_model=ReviewResultRead)
def manual_review(
    review_result_public_id: str,
    payload: ManualReviewUpdate,
    session: Session = Depends(get_db),
) -> ReviewResultRead:
    service = ReviewRunService(session)
    result = service.manual_review(review_result_public_id=review_result_public_id, **payload.model_dump())
    return review_result_read(result)


@router.post("/review-runs/{review_run_public_id}/retry-failed", response_model=ReviewRunRead)
def retry_failed(review_run_public_id: str, session: Session = Depends(get_db)) -> ReviewRunRead:
    service = ReviewRunService(session)
    return review_run_read(service.retry_failed(review_run_public_id=review_run_public_id))


@router.post("/review-runs/{review_run_public_id}/publish", response_model=ApprovalTaskRead)
def publish_review_run(review_run_public_id: str, session: Session = Depends(get_db)) -> ApprovalTaskRead:
    service = ReviewRunService(session)
    task = service.publish(review_run_public_id=review_run_public_id)
    return approval_task_read(task)
