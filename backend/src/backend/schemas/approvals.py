from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import TimestampedPublicRead


class ApprovalDecisionRequest(BaseModel):
    operator_note: str | None = None


class ApprovalItemRead(TimestampedPublicRead):
    approval_task_public_id: str
    item_type: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    risk_level: str


class ApprovalTaskRead(TimestampedPublicRead):
    object_type: str
    object_public_id: str
    action_type: str
    status: str
    title: str
    summary: str | None
    command_preview: list[dict[str, Any]] = Field(default_factory=list)
    operator_note: str | None = None
    items: list[ApprovalItemRead] = Field(default_factory=list)
