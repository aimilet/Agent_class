from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin


class ApprovalTask(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "approval_task"
    public_id_prefix = "apt"

    object_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_public_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    command_preview_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operator_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    items: Mapped[list["ApprovalItem"]] = relationship(back_populates="approval_task", cascade="all, delete-orphan")


class ApprovalItem(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "approval_item"
    public_id_prefix = "api"

    approval_task_id: Mapped[int] = mapped_column(ForeignKey("approval_task.id"), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(64), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")

    approval_task: Mapped[ApprovalTask] = relationship(back_populates="items")


class AgentRun(IntegerPrimaryKeyMixin, PublicIdMixin, Base):
    __tablename__ = "agent_run"
    public_id_prefix = "agr"

    graph_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    stage_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_ref_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_ref_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tool_calls: Mapped[list["ToolCallLog"]] = relationship(back_populates="agent_run", cascade="all, delete-orphan")


class ToolCallLog(IntegerPrimaryKeyMixin, PublicIdMixin, Base):
    __tablename__ = "tool_call_log"
    public_id_prefix = "tcl"

    agent_run_id: Mapped[int] = mapped_column(ForeignKey("agent_run.id"), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    command_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    arguments_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    stdout_ref: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    stderr_ref: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent_run: Mapped[AgentRun] = relationship(back_populates="tool_calls")


class AuditEvent(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "audit_event"
    public_id_prefix = "audit"

    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_public_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
