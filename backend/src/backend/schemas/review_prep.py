from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import FileRefRead, TimestampedPublicRead


class ReviewPrepCreate(BaseModel):
    material_paths: list[str] = Field(default_factory=list)


class ReviewPrepRead(TimestampedPublicRead):
    assignment_public_id: str
    status: str
    source_materials: list[FileRefRead]
    version_no: int
    confirmed_at: datetime | None = None


class ReviewQuestionItemRead(TimestampedPublicRead):
    review_prep_public_id: str
    question_no: int
    question_full_text: str
    reference_answer_short: str | None
    reference_answer_full: str | None
    rubric_text: str | None
    score_weight: float
    status: str


class ReviewQuestionItemPatch(BaseModel):
    question_full_text: str | None = None
    reference_answer_short: str | None = None
    reference_answer_full: str | None = None
    rubric_text: str | None = None
    score_weight: float | None = None
    status: str | None = None


class ReviewAnswerRoundRead(TimestampedPublicRead):
    review_prep_public_id: str
    question_item_public_id: str
    round_no: int
    generator_output: dict[str, Any] | None = None
    critic_feedback: dict[str, Any] | None = None
    judge_result: dict[str, Any] | None = None
    status: str
