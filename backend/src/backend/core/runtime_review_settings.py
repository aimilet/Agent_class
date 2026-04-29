from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from backend.core.settings import Settings, get_settings


class RuntimeReviewSettings(BaseModel):
    review_prep_max_answer_rounds: int = Field(default=3, ge=1, le=8)
    review_run_enable_validation_agent: bool = True
    review_run_default_parallelism: int = Field(default=4, ge=1, le=32)
    default_review_scale: int = Field(default=100, ge=1, le=1000)
    submission_unpack_max_depth: int = Field(default=4, ge=1, le=10)
    submission_unpack_max_files: int = Field(default=120, ge=1, le=2000)
    vision_max_assets_per_submission: int = Field(default=6, ge=1, le=32)
    llm_timeout_seconds: float = Field(default=120.0, ge=10.0, le=900.0)
    llm_max_retries: int = Field(default=2, ge=0, le=8)


class RuntimeReviewSettingsStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def file_path(self) -> Path:
        return self.settings.resolved_runtime_root / "review_runtime_settings.json"

    def defaults(self) -> RuntimeReviewSettings:
        return RuntimeReviewSettings(
            review_prep_max_answer_rounds=max(1, self.settings.max_answer_rounds),
            review_run_enable_validation_agent=self.settings.review_validation_enabled,
            review_run_default_parallelism=max(1, self.settings.review_parallelism),
            default_review_scale=max(1, self.settings.default_review_scale),
            submission_unpack_max_depth=max(1, self.settings.submission_unpack_max_depth),
            submission_unpack_max_files=max(1, self.settings.submission_unpack_max_files),
            vision_max_assets_per_submission=max(1, self.settings.vision_max_assets_per_submission),
            llm_timeout_seconds=max(10.0, self.settings.llm_timeout_seconds),
            llm_max_retries=max(0, self.settings.llm_max_retries),
        )

    def load(self) -> RuntimeReviewSettings:
        defaults = self.defaults()
        if not self.file_path.exists():
            return defaults
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            return defaults
        if not isinstance(payload, dict):
            return defaults
        merged = {**defaults.model_dump(mode="json"), **payload}
        return RuntimeReviewSettings.model_validate(merged)

    def save(self, config: RuntimeReviewSettings) -> RuntimeReviewSettings:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(
            json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return config
