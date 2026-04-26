from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.repositories import AgentRunRepository, AuditRepository


class AuditQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.agent_run_repo = AgentRunRepository(session)
        self.audit_repo = AuditRepository(session)

    def list_agent_runs(self):
        return self.agent_run_repo.list_runs()

    def get_agent_run(self, agent_run_public_id: str):
        return self.agent_run_repo.get_run(agent_run_public_id)

    def list_tool_calls(self, agent_run_public_id: str):
        run = self.agent_run_repo.get_run(agent_run_public_id)
        return self.agent_run_repo.list_tool_calls(run)

    def list_object_events(self, *, object_type: str, object_public_id: str):
        return self.audit_repo.list_by_object(object_type=object_type, object_public_id=object_public_id)
