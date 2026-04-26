from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class TimestampedPublicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    created_at: datetime
    updated_at: datetime


class FileRefRead(BaseModel):
    original_name: str
    stored_name: str
    path: str
    size_bytes: int


class AgentRunContext(BaseModel):
    graph_name: str
    stage_name: str
    run_id: str
    course_id: str | None = None
    assignment_id: str | None = None
    review_prep_id: str | None = None
    submission_id: str | None = None
    prompt_version: str
    model_name: str | None = None


class AgentTaskContext(BaseModel):
    locale: str = "zh-CN"
    now: datetime
    operator_id: str = "system"


class AgentConstraints(BaseModel):
    must_return_json: bool = True
    allow_tool_calls: bool = False
    max_output_tokens: int = 4000
    cannot_write_db: bool = True
    cannot_execute_filesystem_mutation: bool = True


class AgentInputEnvelope(BaseModel):
    run_context: AgentRunContext
    task_context: AgentTaskContext
    constraints: AgentConstraints = Field(default_factory=AgentConstraints)
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentOutputEnvelope(BaseModel):
    status: str = "succeeded"
    confidence: float = 0.0
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    needs_review: bool = False
    structured_output: dict[str, Any] = Field(default_factory=dict)
    proposed_operations: list[dict[str, Any]] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
