from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import TimestampedPublicRead


class NamingPolicyCreate(BaseModel):
    template_text: str | None = None
    natural_language_rule: str | None = None


class NamingPolicyRead(TimestampedPublicRead):
    assignment_public_id: str
    template_text: str
    natural_language_rule: str | None
    version_no: int
    created_by_agent_run_id: str | None = None
    status: str


class NamingPlanCreate(BaseModel):
    policy_public_id: str | None = None
    template_text: str | None = None
    natural_language_rule: str | None = None


class NamingOperationRead(TimestampedPublicRead):
    plan_public_id: str
    submission_public_id: str
    source_path: str
    target_path: str
    status: str
    conflict_strategy: str | None
    command_preview: str | None
    rollback_info: dict[str, Any] | None = None


class NamingPlanRead(TimestampedPublicRead):
    assignment_public_id: str
    policy_public_id: str
    status: str
    approval_task_public_id: str | None = None
    summary: dict[str, Any] | None = None
    operations: list[NamingOperationRead] = Field(default_factory=list)
