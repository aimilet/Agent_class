from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.audits import AgentRunRead, AuditEventRead, ToolCallLogRead
from backend.services.audits import AuditQueryService
from backend.services.serializers import agent_run_read, audit_event_read, tool_call_log_read


router = APIRouter(tags=["audits"])


@router.get("/agent-runs", response_model=list[AgentRunRead])
def list_agent_runs(session: Session = Depends(get_db)) -> list[AgentRunRead]:
    service = AuditQueryService(session)
    return [agent_run_read(item) for item in service.list_agent_runs()]


@router.get("/agent-runs/{agent_run_public_id}", response_model=AgentRunRead)
def get_agent_run(agent_run_public_id: str, session: Session = Depends(get_db)) -> AgentRunRead:
    service = AuditQueryService(session)
    return agent_run_read(service.get_agent_run(agent_run_public_id))


@router.get("/agent-runs/{agent_run_public_id}/tool-calls", response_model=list[ToolCallLogRead])
def list_tool_calls(agent_run_public_id: str, session: Session = Depends(get_db)) -> list[ToolCallLogRead]:
    service = AuditQueryService(session)
    return [tool_call_log_read(item) for item in service.list_tool_calls(agent_run_public_id)]


@router.get("/courses/{course_public_id}/audit-events", response_model=list[AuditEventRead])
def list_course_audits(course_public_id: str, session: Session = Depends(get_db)) -> list[AuditEventRead]:
    service = AuditQueryService(session)
    return [audit_event_read(item) for item in service.list_object_events(object_type="course", object_public_id=course_public_id)]


@router.get("/submissions/{submission_public_id}/audit-events", response_model=list[AuditEventRead])
def list_submission_audits(submission_public_id: str, session: Session = Depends(get_db)) -> list[AuditEventRead]:
    service = AuditQueryService(session)
    return [audit_event_read(item) for item in service.list_object_events(object_type="submission", object_public_id=submission_public_id)]


@router.get("/objects/{object_type}/{object_public_id}/logs", response_model=list[AuditEventRead])
def list_object_logs(object_type: str, object_public_id: str, session: Session = Depends(get_db)) -> list[AuditEventRead]:
    service = AuditQueryService(session)
    return [audit_event_read(item) for item in service.list_object_events(object_type=object_type, object_public_id=object_public_id)]
