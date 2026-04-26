from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    graph_name: str
    agent_name: str
    stage_name: str
    status: str
    model_name: str | None
    prompt_version: str | None
    input_ref_json: dict[str, Any] | None
    output_ref_json: dict[str, Any] | None
    error_message: str | None
    started_at: datetime
    ended_at: datetime | None


class ToolCallLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    agent_run_id: int
    tool_name: str
    command_text: str | None
    arguments_json: dict[str, Any] | None
    stdout_ref: str | None
    stderr_ref: str | None
    exit_code: int | None
    status: str
    started_at: datetime
    ended_at: datetime | None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    event_type: str
    object_type: str
    object_public_id: str
    actor_type: str
    actor_id: str | None
    event_payload_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
