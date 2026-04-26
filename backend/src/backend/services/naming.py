from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.core.errors import DomainError
from backend.db.repositories import ApprovalRepository, AssignmentRepository, SubmissionRepository
from backend.domain.models import NamingOperation, NamingPlan, NamingPolicy
from backend.domain.state_machine import ensure_transition
from backend.graphs.naming_plan_graph import NamingPlanGraph
from backend.infra.file_ops import execute_rename
from backend.infra.observability import AuditService


class NamingService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.assignment_repo = AssignmentRepository(session)
        self.submission_repo = SubmissionRepository(session)
        self.approval_repo = ApprovalRepository(session)
        self.audit_service = AuditService(session)

    def create_policy(self, *, assignment_public_id: str, template_text: str | None, natural_language_rule: str | None):
        assignment = self.assignment_repo.get_by_public_id(assignment_public_id)
        current_version = (
            self.session.scalar(
                select(NamingPolicy.version_no)
                .where(NamingPolicy.assignment_id == assignment.id)
                .order_by(NamingPolicy.version_no.desc())
                .limit(1)
            )
            or 0
        )
        for existing in self.session.scalars(
            select(NamingPolicy).where(NamingPolicy.assignment_id == assignment.id, NamingPolicy.status == "active")
        ).all():
            existing.status = "superseded"
        policy = NamingPolicy(
            public_id=NamingPolicy.build_public_id(),
            assignment_id=assignment.id,
            template_text=template_text or "{assignment}_{student_no}_{name}",
            natural_language_rule=natural_language_rule,
            version_no=current_version + 1,
            status="active",
        )
        self.session.add(policy)
        self.audit_service.record(
            event_type="naming_policy_created",
            object_type="naming_policy",
            object_public_id=policy.public_id,
            payload={"assignment_public_id": assignment.public_id},
        )
        self.session.commit()
        self.session.refresh(policy)
        return policy

    def list_policies(self, assignment_public_id: str):
        assignment = self.assignment_repo.get_by_public_id(assignment_public_id)
        return list(
            self.session.scalars(
                select(NamingPolicy)
                .where(NamingPolicy.assignment_id == assignment.id)
                .order_by(NamingPolicy.version_no.desc())
            ).all()
        )

    def create_plan(
        self,
        *,
        assignment_public_id: str,
        policy_public_id: str | None,
        template_text: str | None,
        natural_language_rule: str | None,
        operator_id: str = "system",
    ):
        assignment = self.assignment_repo.get_by_public_id(assignment_public_id)
        policy = None
        if policy_public_id:
            policy = self.session.scalar(select(NamingPolicy).where(NamingPolicy.public_id == policy_public_id))
            if policy is None:
                raise DomainError("命名策略不存在。", code="naming_policy_not_found", status_code=404)
        if policy is None:
            graph = NamingPlanGraph(self.session)
            graph_state = graph.invoke(
                assignment_public_id=assignment.public_id,
                policy_public_id=None,
                template_text=template_text,
                natural_language_rule=natural_language_rule,
                operator_id=operator_id,
            )
            policy = self.create_policy(
                assignment_public_id=assignment.public_id,
                template_text=graph_state["normalized_template"],
                natural_language_rule=natural_language_rule,
            )
            operations = graph_state["operations"]
        else:
            graph = NamingPlanGraph(self.session)
            graph_state = graph.invoke(
                assignment_public_id=assignment.public_id,
                policy_public_id=policy.public_id,
                template_text=policy.template_text,
                natural_language_rule=policy.natural_language_rule,
                operator_id=operator_id,
            )
            operations = graph_state["operations"]

        plan = NamingPlan(
            public_id=NamingPlan.build_public_id(),
            assignment_id=assignment.id,
            policy_id=policy.id,
            status="generated",
            summary_json={"operation_count": len(operations)},
        )
        self.session.add(plan)
        self.session.flush()
        for item in operations:
            self.session.add(
                NamingOperation(
                    public_id=NamingOperation.build_public_id(),
                    plan_id=plan.id,
                    submission_id=item["submission_id"],
                    source_path=item["source_path"],
                    target_path=item["target_path"],
                    status=item["status"],
                    conflict_strategy=item.get("conflict_strategy"),
                    command_preview=item.get("command_preview"),
                )
            )
        assignment.status = "naming_ready"
        self.audit_service.record(
            event_type="naming_plan_created",
            object_type="naming_plan",
            object_public_id=plan.public_id,
            actor_type="user",
            actor_id=operator_id,
            payload={"assignment_public_id": assignment.public_id},
        )
        self.session.commit()
        return self.get_plan(plan.public_id)

    def get_plan(self, plan_public_id: str):
        plan = self.session.scalar(
            select(NamingPlan)
            .options(
                selectinload(NamingPlan.assignment),
                selectinload(NamingPlan.policy),
                selectinload(NamingPlan.operations).selectinload(NamingOperation.submission),
            )
            .where(NamingPlan.public_id == plan_public_id)
        )
        if plan is None:
            raise DomainError("命名计划不存在。", code="naming_plan_not_found", status_code=404)
        return plan

    def submit_approval(self, *, plan_public_id: str, operator_id: str = "system"):
        plan = self.get_plan(plan_public_id)
        if plan.approval_task_id is not None:
            raise DomainError("命名计划已提交审批。", code="naming_plan_already_submitted", status_code=409)
        command_preview = [
            {"operation_public_id": operation.public_id, "command": operation.command_preview}
            for operation in plan.operations
        ]
        task = self.approval_repo.create(
            object_type="naming_plan",
            object_public_id=plan.public_id,
            action_type="execute",
            title="批量命名修正审批",
            summary=f"共 {len(plan.operations)} 条命名修正操作等待审批。",
            command_preview_json=command_preview,
        )
        for operation in plan.operations:
            self.approval_repo.add_item(
                task,
                item_type="rename",
                before_json={"path": operation.source_path},
                after_json={"path": operation.target_path},
                risk_level="medium",
            )
        ensure_transition("naming_plan", plan.status, "pending_approval")
        plan.status = "pending_approval"
        plan.approval_task_id = task.id
        self.audit_service.record(
            event_type="naming_plan_submitted_for_approval",
            object_type="naming_plan",
            object_public_id=plan.public_id,
            actor_type="user",
            actor_id=operator_id,
            payload={"approval_task_public_id": task.public_id},
        )
        self.session.commit()
        return task

    def execute_plan(self, *, plan_public_id: str, operator_id: str = "system"):
        plan = self.get_plan(plan_public_id)
        if plan.approval_task is None or plan.approval_task.status != "approved":
            raise DomainError("命名计划尚未审批通过。", code="approval_required", status_code=409)
        ensure_transition("naming_plan", plan.status, "executing")
        plan.status = "executing"
        renamed_count = 0
        conflict_count = 0
        for operation in plan.operations:
            if operation.status not in {"planned", "approved"}:
                continue
            result = execute_rename(operation.source_path, operation.target_path)
            if result.executed:
                operation.status = "renamed"
                operation.executed_at = datetime.now(UTC)
                operation.rollback_info_json = {
                    "source_path": result.source_path,
                    "target_path": result.target_path,
                }
                operation.submission.current_path = result.target_path
                operation.submission.canonical_name = operation.target_path.split("/")[-1]
                operation.submission.status = "named"
                renamed_count += 1
            else:
                operation.status = "conflicted"
                operation.rollback_info_json = {"reason": result.reason}
                conflict_count += 1
        plan.status = "applied" if conflict_count == 0 else "partially_applied"
        plan.summary_json = {
            "renamed_count": renamed_count,
            "conflict_count": conflict_count,
        }
        self.audit_service.record(
            event_type="naming_plan_executed",
            object_type="naming_plan",
            object_public_id=plan.public_id,
            actor_type="user",
            actor_id=operator_id,
            payload=plan.summary_json,
        )
        self.session.commit()
        return self.get_plan(plan.public_id)

    def rollback_plan(self, *, plan_public_id: str, operator_id: str = "system"):
        plan = self.get_plan(plan_public_id)
        for operation in plan.operations:
            rollback = operation.rollback_info_json or {}
            source_path = rollback.get("source_path")
            target_path = rollback.get("target_path")
            if operation.status != "renamed" or not source_path or not target_path:
                continue
            result = execute_rename(target_path, source_path)
            if result.executed:
                operation.status = "rolled_back"
                operation.submission.current_path = source_path
        plan.status = "rolled_back"
        self.audit_service.record(
            event_type="naming_plan_rolled_back",
            object_type="naming_plan",
            object_public_id=plan.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        return self.get_plan(plan.public_id)
