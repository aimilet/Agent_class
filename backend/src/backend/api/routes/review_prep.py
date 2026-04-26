from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.review_prep import ReviewPrepRead, ReviewQuestionItemPatch, ReviewQuestionItemRead
from backend.services.review_prep import ReviewPrepService
from backend.services.serializers import review_prep_read, review_question_item_read


router = APIRouter(tags=["review-prep"])


@router.post("/assignments/{assignment_public_id}/review-preps", response_model=ReviewPrepRead)
async def create_review_prep(
    assignment_public_id: str,
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_db),
) -> ReviewPrepRead:
    service = ReviewPrepService(session)
    review_prep = await service.create_review_prep(assignment_public_id=assignment_public_id, files=files)
    return review_prep_read(review_prep)


@router.post("/review-preps/{review_prep_public_id}/run", response_model=ReviewPrepRead)
def run_review_prep(review_prep_public_id: str, session: Session = Depends(get_db)) -> ReviewPrepRead:
    service = ReviewPrepService(session)
    return review_prep_read(service.run_review_prep(review_prep_public_id=review_prep_public_id))


@router.get("/review-preps/{review_prep_public_id}", response_model=ReviewPrepRead)
def get_review_prep(review_prep_public_id: str, session: Session = Depends(get_db)) -> ReviewPrepRead:
    service = ReviewPrepService(session)
    return review_prep_read(service.get_review_prep(review_prep_public_id))


@router.get("/review-preps/{review_prep_public_id}/questions", response_model=list[ReviewQuestionItemRead])
def list_review_questions(review_prep_public_id: str, session: Session = Depends(get_db)) -> list[ReviewQuestionItemRead]:
    service = ReviewPrepService(session)
    return [review_question_item_read(item) for item in service.list_questions(review_prep_public_id)]


@router.patch("/review-question-items/{item_public_id}", response_model=ReviewQuestionItemRead)
def patch_review_question(
    item_public_id: str,
    payload: ReviewQuestionItemPatch,
    session: Session = Depends(get_db),
) -> ReviewQuestionItemRead:
    service = ReviewPrepService(session)
    item = service.patch_question(item_public_id=item_public_id, payload=payload.model_dump())
    return review_question_item_read(item)


@router.post("/review-preps/{review_prep_public_id}/confirm", response_model=ReviewPrepRead)
def confirm_review_prep(review_prep_public_id: str, session: Session = Depends(get_db)) -> ReviewPrepRead:
    service = ReviewPrepService(session)
    return review_prep_read(service.confirm_review_prep(review_prep_public_id=review_prep_public_id))
