from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewRuntimeSettingsRead(BaseModel):
    review_prep_max_answer_rounds: int = Field(ge=1, le=8)
    review_run_enable_validation_agent: bool
    review_run_default_parallelism: int = Field(ge=1, le=32)


class ReviewRuntimeSettingsUpdate(BaseModel):
    review_prep_max_answer_rounds: int = Field(ge=1, le=8)
    review_run_enable_validation_agent: bool
    review_run_default_parallelism: int = Field(ge=1, le=32)


class HealthResponse(BaseModel):
    app_name: str
    database_url: str
    runtime_root: str
    llm_enabled: bool
    review_runtime_settings: ReviewRuntimeSettingsRead
