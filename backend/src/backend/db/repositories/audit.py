from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.errors import DomainError
from backend.domain.models import AgentRun, ApprovalItem, ApprovalTask, AuditEvent, ToolCallLog


class AgentRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        graph_name: str,
        agent_name: str,
        stage_name: str,
        status: str = "queued",
        model_name: str | None = None,
        prompt_version: str | None = None,
        input_ref_json: dict[str, Any] | None = None,
    ) -> AgentRun:
        run = AgentRun(
            public_id=AgentRun.build_public_id(),
            graph_name=graph_name,
            agent_name=agent_name,
            stage_name=stage_name,
            status=status,
            model_name=model_name,
            prompt_version=prompt_version,
            input_ref_json=input_ref_json,
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish(
        self,
        run: AgentRun,
        *,
        status: str,
        output_ref_json: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> AgentRun:
        run.status = status
        run.output_ref_json = output_ref_json
        run.error_message = error_message
        run.ended_at = datetime.now(UTC)
        self.session.flush()
        return run

    def list_runs(self) -> list[AgentRun]:
        return list(self.session.scalars(select(AgentRun).order_by(AgentRun.started_at.desc())).all())

    def get_run(self, public_id: str) -> AgentRun:
        run = self.session.scalar(select(AgentRun).where(AgentRun.public_id == public_id))
        if run is None:
            raise DomainError("Agent 运行记录不存在。", code="agent_run_not_found", status_code=404)
        return run

    def list_tool_calls(self, run: AgentRun) -> list[ToolCallLog]:
        return list(
            self.session.scalars(
                select(ToolCallLog)
                .where(ToolCallLog.agent_run_id == run.id)
                .order_by(ToolCallLog.started_at.asc())
            ).all()
        )


class ApprovalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        object_type: str,
        object_public_id: str,
        action_type: str,
        title: str,
        summary: str | None,
        command_preview_json: list[dict[str, Any]],
    ) -> ApprovalTask:
        task = ApprovalTask(
            public_id=ApprovalTask.build_public_id(),
            object_type=object_type,
            object_public_id=object_public_id,
            action_type=action_type,
            title=title,
            summary=summary,
            command_preview_json=command_preview_json,
            status="pending",
        )
        self.session.add(task)
        self.session.flush()
        return task

    def add_item(
        self,
        task: ApprovalTask,
        *,
        item_type: str,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
        risk_level: str,
    ) -> ApprovalItem:
        item = ApprovalItem(
            public_id=ApprovalItem.build_public_id(),
            approval_task_id=task.id,
            item_type=item_type,
            before_json=before_json,
            after_json=after_json,
            risk_level=risk_level,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def get_task(self, public_id: str) -> ApprovalTask:
        task = self.session.scalar(select(ApprovalTask).where(ApprovalTask.public_id == public_id))
        if task is None:
            raise DomainError("审批任务不存在。", code="approval_task_not_found", status_code=404)
        return task


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_object(self, *, object_type: str, object_public_id: str) -> list[AuditEvent]:
        return list(
            self.session.scalars(
                select(AuditEvent)
                .where(AuditEvent.object_type == object_type, AuditEvent.object_public_id == object_public_id)
                .order_by(AuditEvent.created_at.desc())
            ).all()
        )
