from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.models import ToolCallLog


class ToolCallRecorder:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start(
        self,
        *,
        agent_run_id: int,
        tool_name: str,
        command_text: str | None = None,
        arguments_json: dict[str, Any] | None = None,
    ) -> ToolCallLog:
        log = ToolCallLog(
            public_id=ToolCallLog.build_public_id(),
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            command_text=command_text,
            arguments_json=arguments_json,
            status="running",
            started_at=datetime.now(UTC),
        )
        self.session.add(log)
        self.session.flush()
        return log

    def finish(
        self,
        log: ToolCallLog,
        *,
        status: str,
        stdout_ref: str | None = None,
        stderr_ref: str | None = None,
        exit_code: int | None = None,
    ) -> ToolCallLog:
        log.status = status
        log.stdout_ref = stdout_ref
        log.stderr_ref = stderr_ref
        log.exit_code = exit_code
        log.ended_at = datetime.now(UTC)
        self.session.flush()
        return log
