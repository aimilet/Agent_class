from __future__ import annotations

from fastapi import APIRouter

from backend.core.runtime_review_settings import RuntimeReviewSettings, RuntimeReviewSettingsStore
from backend.core.settings import get_settings
from backend.schemas.system import HealthResponse, ReviewRuntimeSettingsRead, ReviewRuntimeSettingsUpdate


router = APIRouter(tags=["system"])


@router.get("/")
def index() -> dict[str, str]:
    return {"message": "助教 Agent 后端已启动。"}


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    runtime_settings = RuntimeReviewSettingsStore(settings).load()
    return HealthResponse(
        app_name=settings.app_name,
        database_url=settings.resolved_database_url,
        runtime_root=str(settings.resolved_runtime_root),
        llm_enabled=settings.llm_enabled,
        review_runtime_settings=ReviewRuntimeSettingsRead.model_validate(runtime_settings.model_dump(mode="json")),
    )


@router.get("/system/review-settings", response_model=ReviewRuntimeSettingsRead)
def get_review_settings() -> ReviewRuntimeSettingsRead:
    settings = RuntimeReviewSettingsStore(get_settings()).load()
    return ReviewRuntimeSettingsRead.model_validate(settings.model_dump(mode="json"))


@router.put("/system/review-settings", response_model=ReviewRuntimeSettingsRead)
def update_review_settings(payload: ReviewRuntimeSettingsUpdate) -> ReviewRuntimeSettingsRead:
    store = RuntimeReviewSettingsStore(get_settings())
    settings = store.save(RuntimeReviewSettings.model_validate(payload.model_dump()))
    return ReviewRuntimeSettingsRead.model_validate(settings.model_dump(mode="json"))
