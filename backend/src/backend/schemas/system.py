from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewRuntimeSettingsRead(BaseModel):
    review_prep_max_answer_rounds: int = Field(ge=1, le=8)
    review_run_enable_validation_agent: bool
    review_run_default_parallelism: int = Field(ge=1, le=32)
    default_review_scale: int = Field(ge=1, le=1000)
    submission_unpack_max_depth: int = Field(ge=1, le=10)
    submission_unpack_max_files: int = Field(ge=1, le=2000)
    vision_max_assets_per_submission: int = Field(ge=1, le=32)
    llm_timeout_seconds: float = Field(ge=10.0, le=900.0)
    llm_max_retries: int = Field(ge=0, le=8)


class ReviewRuntimeSettingsUpdate(BaseModel):
    review_prep_max_answer_rounds: int = Field(ge=1, le=8)
    review_run_enable_validation_agent: bool
    review_run_default_parallelism: int = Field(ge=1, le=32)
    default_review_scale: int = Field(ge=1, le=1000)
    submission_unpack_max_depth: int = Field(ge=1, le=10)
    submission_unpack_max_files: int = Field(ge=1, le=2000)
    vision_max_assets_per_submission: int = Field(ge=1, le=32)
    llm_timeout_seconds: float = Field(ge=10.0, le=900.0)
    llm_max_retries: int = Field(ge=0, le=8)


class HealthResponse(BaseModel):
    app_name: str
    database_url: str
    runtime_root: str
    llm_enabled: bool
    review_runtime_settings: ReviewRuntimeSettingsRead
