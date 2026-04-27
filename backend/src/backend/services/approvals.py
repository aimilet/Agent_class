from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.core.errors import DomainError
from backend.db.repositories import ApprovalRepository
from backend.domain.models import NamingPlan, ReviewRun
from backend.infra.observability import AuditService


class ApprovalService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.approval_repo = ApprovalRepository(session)
        self.audit_service = AuditService(session)

    def get_task(self, approval_task_public_id: str):
        return self.approval_repo.get_task(approval_task_public_id)

    def approve(self, *, approval_task_public_id: str, operator_note: str | None, operator_id: str = "system"):
        task = self.approval_repo.get_task(approval_task_public_id)
        if task.status == "approved":
            return task
        if task.status != "pending":
            raise DomainError("审批任务当前不可批准。", code="approval_task_invalid_status", status_code=409)
        task.status = "approved"
        task.approved_at = datetime.now(UTC)
        task.operator_note = operator_note
        if task.object_type == "naming_plan":
            plan = self.session.scalar(select(NamingPlan).where(NamingPlan.public_id == task.object_public_id))
            if plan is not None:
                plan.status = "approved"
                for operation in plan.operations:
                    operation.status = "approved"
        self.audit_service.record(
            event_type="approval_task_approved",
            object_type="approval_task",
            object_public_id=task.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        return task

    def reject(self, *, approval_task_public_id: str, operator_note: str | None, operator_id: str = "system"):
        task = self.approval_repo.get_task(approval_task_public_id)
        if task.status == "rejected":
            return task
        if task.status != "pending":
            raise DomainError("审批任务当前不可拒绝。", code="approval_task_invalid_status", status_code=409)
        task.status = "rejected"
        task.rejected_at = datetime.now(UTC)
        task.operator_note = operator_note
        if task.object_type == "naming_plan":
            plan = self.session.scalar(select(NamingPlan).where(NamingPlan.public_id == task.object_public_id))
            if plan is not None:
                plan.status = "rejected"
        self.audit_service.record(
            event_type="approval_task_rejected",
            object_type="approval_task",
            object_public_id=task.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        return task

    def execute_approved_side_effects(self, *, approval_task_public_id: str, operator_id: str = "system"):
        task = self.approval_repo.get_task(approval_task_public_id)
        if task.status != "approved":
            raise DomainError("审批任务尚未通过。", code="approval_task_not_approved", status_code=409)
        if task.object_type == "review_run" and task.action_type == "publish":
            review_run = self.session.scalar(
                select(ReviewRun)
                .options(selectinload(ReviewRun.results), selectinload(ReviewRun.assignment))
                .where(ReviewRun.public_id == task.object_public_id)
            )
            if review_run is None:
                raise DomainError("评审运行不存在。", code="review_run_not_found", status_code=404)
            task.status = "executing"
            for result in review_run.results:
                result.status = "published"
                result.published_at = datetime.now(UTC)
                result.submission.status = "published"
            review_run.status = "completed"
            review_run.assignment.status = "published"
            task.status = "executed"
        self.audit_service.record(
            event_type="approval_task_executed",
            object_type="approval_task",
            object_public_id=task.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        return task
