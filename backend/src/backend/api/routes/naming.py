from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.approvals import ApprovalTaskRead
from backend.schemas.naming import NamingPlanCreate, NamingPlanRead, NamingPolicyCreate, NamingPolicyRead
from backend.services.naming import NamingService
from backend.services.serializers import approval_task_read, naming_plan_read, naming_policy_read


router = APIRouter(tags=["naming"])


@router.post("/assignments/{assignment_public_id}/naming-policies", response_model=NamingPolicyRead)
def create_naming_policy(
    assignment_public_id: str,
    payload: NamingPolicyCreate,
    session: Session = Depends(get_db),
) -> NamingPolicyRead:
    service = NamingService(session)
    policy = service.create_policy(assignment_public_id=assignment_public_id, **payload.model_dump())
    return naming_policy_read(policy)


@router.get("/assignments/{assignment_public_id}/naming-policies", response_model=list[NamingPolicyRead])
def list_naming_policies(assignment_public_id: str, session: Session = Depends(get_db)) -> list[NamingPolicyRead]:
    service = NamingService(session)
    return [naming_policy_read(item) for item in service.list_policies(assignment_public_id)]


@router.post("/assignments/{assignment_public_id}/naming-plans", response_model=NamingPlanRead)
def create_naming_plan(
    assignment_public_id: str,
    payload: NamingPlanCreate,
    session: Session = Depends(get_db),
) -> NamingPlanRead:
    service = NamingService(session)
    plan = service.create_plan(assignment_public_id=assignment_public_id, **payload.model_dump())
    return naming_plan_read(plan)


@router.get("/naming-plans/{plan_public_id}", response_model=NamingPlanRead)
def get_naming_plan(plan_public_id: str, session: Session = Depends(get_db)) -> NamingPlanRead:
    service = NamingService(session)
    return naming_plan_read(service.get_plan(plan_public_id))


@router.post("/naming-plans/{plan_public_id}/submit-approval", response_model=ApprovalTaskRead)
def submit_naming_plan_approval(plan_public_id: str, session: Session = Depends(get_db)) -> ApprovalTaskRead:
    service = NamingService(session)
    task = service.submit_approval(plan_public_id=plan_public_id)
    return approval_task_read(task)


@router.post("/naming-plans/{plan_public_id}/execute", response_model=NamingPlanRead)
def execute_naming_plan(plan_public_id: str, session: Session = Depends(get_db)) -> NamingPlanRead:
    service = NamingService(session)
    return naming_plan_read(service.execute_plan(plan_public_id=plan_public_id))


@router.post("/naming-plans/{plan_public_id}/rollback", response_model=NamingPlanRead)
def rollback_naming_plan(plan_public_id: str, session: Session = Depends(get_db)) -> NamingPlanRead:
    service = NamingService(session)
    return naming_plan_read(service.rollback_plan(plan_public_id=plan_public_id))
