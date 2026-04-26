from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.approvals import ApprovalDecisionRequest, ApprovalTaskRead
from backend.services.approvals import ApprovalService
from backend.services.serializers import approval_task_read


router = APIRouter(tags=["approvals"])


@router.get("/approval-tasks/{approval_task_public_id}", response_model=ApprovalTaskRead)
def get_approval_task(approval_task_public_id: str, session: Session = Depends(get_db)) -> ApprovalTaskRead:
    service = ApprovalService(session)
    return approval_task_read(service.get_task(approval_task_public_id))


@router.post("/approval-tasks/{approval_task_public_id}/approve", response_model=ApprovalTaskRead)
def approve_task(
    approval_task_public_id: str,
    payload: ApprovalDecisionRequest,
    session: Session = Depends(get_db),
) -> ApprovalTaskRead:
    service = ApprovalService(session)
    task = service.approve(
        approval_task_public_id=approval_task_public_id,
        operator_note=payload.operator_note,
    )
    return approval_task_read(task)


@router.post("/approval-tasks/{approval_task_public_id}/reject", response_model=ApprovalTaskRead)
def reject_task(
    approval_task_public_id: str,
    payload: ApprovalDecisionRequest,
    session: Session = Depends(get_db),
) -> ApprovalTaskRead:
    service = ApprovalService(session)
    task = service.reject(
        approval_task_public_id=approval_task_public_id,
        operator_note=payload.operator_note,
    )
    return approval_task_read(task)


@router.post("/approval-tasks/{approval_task_public_id}/execute", response_model=ApprovalTaskRead)
def execute_task(approval_task_public_id: str, session: Session = Depends(get_db)) -> ApprovalTaskRead:
    service = ApprovalService(session)
    task = service.execute_approved_side_effects(approval_task_public_id=approval_task_public_id)
    return approval_task_read(task)
