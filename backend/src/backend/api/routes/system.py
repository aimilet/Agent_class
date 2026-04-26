from __future__ import annotations

from fastapi import APIRouter

from backend.core.settings import get_settings


router = APIRouter(tags=["system"])


@router.get("/")
def index() -> dict[str, str]:
    return {"message": "助教 Agent 后端已启动。"}


@router.get("/health")
def health() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "app_name": settings.app_name,
        "database_url": settings.resolved_database_url,
        "runtime_root": str(settings.resolved_runtime_root),
        "llm_enabled": settings.llm_enabled,
    }
