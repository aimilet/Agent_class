from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import TimestampedPublicRead


class ReviewRunCreate(BaseModel):
    review_prep_public_id: str | None = None
    parallelism: int | None = Field(default=None, ge=1)


class ReviewRunRead(TimestampedPublicRead):
    assignment_public_id: str
    review_prep_public_id: str
    status: str
    parallelism: int
    summary: dict[str, Any] | None = None


class ReviewItemResultRead(TimestampedPublicRead):
    review_result_public_id: str
    question_item_public_id: str
    score: float
    reason: str | None
    evidence: dict[str, Any] | None = None


class ReviewResultRead(TimestampedPublicRead):
    review_run_public_id: str
    submission_public_id: str
    enrollment_public_id: str | None = None
    student_no: str | None = None
    student_name: str | None = None
    source_entry_name: str
    current_path: str
    total_score: float | None
    score_scale: int
    summary: str | None
    decision: str | None
    confidence: float | None
    status: str
    result: dict[str, Any] | None = None
    items: list[ReviewItemResultRead] = Field(default_factory=list)


class ManualReviewUpdate(BaseModel):
    total_score: float = Field(ge=0.0, le=100.0)
    summary: str
    decision: str = "manual_reviewed"
