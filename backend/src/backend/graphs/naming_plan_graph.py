from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from backend.agents import NamingPolicyAgent
from backend.agents.base import AgentExecutor
from backend.db.repositories import ApprovalRepository, AssignmentRepository, SubmissionRepository
from backend.graphs.common import compile_graph
from backend.infra.file_ops import preview_rename_command
from backend.infra.observability import AuditService
from backend.schemas.common import AgentInputEnvelope, AgentRunContext, AgentTaskContext


class NamingPlanGraphInput(TypedDict):
    assignment_public_id: str
    policy_public_id: str | None
    template_text: str | None
    natural_language_rule: str | None
    operator_id: str


class NamingPlanState(NamingPlanGraphInput, total=False):
    submissions: list[Any]
    normalized_template: str
    operations: list[dict[str, Any]]
    approval_task_public_id: str | None


class NamingPlanGraph:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.assignment_repo = AssignmentRepository(session)
        self.submission_repo = SubmissionRepository(session)
        self.approval_repo = ApprovalRepository(session)
        self.audit_service = AuditService(session)
        self.agent = NamingPolicyAgent()
        self.agent_executor = AgentExecutor(session)
        self.compiled = compile_graph(
            state_schema=NamingPlanState,
            input_schema=NamingPlanGraphInput,
            output_schema=NamingPlanState,
            name="naming_plan_graph",
            nodes=[
                ("load_current_submissions", self.load_current_submissions),
                ("normalize_policy", self.normalize_policy),
                ("build_naming_plan", self.build_naming_plan),
            ],
            edges=[
                ("load_current_submissions", "normalize_policy"),
                ("normalize_policy", "build_naming_plan"),
            ],
        )

    def invoke(
        self,
        *,
        assignment_public_id: str,
        policy_public_id: str | None = None,
        template_text: str | None = None,
        natural_language_rule: str | None = None,
        operator_id: str = "system",
    ) -> dict[str, Any]:
        state: NamingPlanGraphInput = {
            "assignment_public_id": assignment_public_id,
            "policy_public_id": policy_public_id,
            "template_text": template_text,
            "natural_language_rule": natural_language_rule,
            "operator_id": operator_id,
        }
        if self.compiled is not None:
            return self.compiled.invoke(state)
        fallback_state: NamingPlanState = dict(state)
        for node in (self.load_current_submissions, self.normalize_policy, self.build_naming_plan):
            fallback_state = node(fallback_state)
        return fallback_state

    def load_current_submissions(self, state: NamingPlanState) -> NamingPlanState:
        assignment = self.assignment_repo.get_by_public_id(state["assignment_public_id"])
        submissions = [
            submission
            for submission in self.submission_repo.list_submissions_by_assignment(assignment)
            if submission.status not in {"ignored", "unmatched"}
        ]
        return {**state, "submissions": submissions}

    def normalize_policy(self, state: NamingPlanState) -> NamingPlanState:
        assignment = self.assignment_repo.get_by_public_id(state["assignment_public_id"])
        envelope = AgentInputEnvelope(
            run_context=AgentRunContext(
                graph_name="naming_plan_graph",
                stage_name="naming_policy_agent",
                run_id=f"naming_plan:{assignment.public_id}",
                assignment_id=assignment.public_id,
                prompt_version=self.agent.prompt_version,
                model_name=self.agent.model_name,
            ),
            task_context=AgentTaskContext(now=datetime.now(), operator_id=state["operator_id"]),
            payload={
                "template_text": state.get("template_text"),
                "natural_language_rule": state.get("natural_language_rule"),
            },
        )
        result = self.agent_executor.run(
            graph_name="naming_plan_graph",
            stage_name="naming_policy_agent",
            agent_name=self.agent.name,
            prompt_version=self.agent.prompt_version,
            model_name=self.agent.model_name,
            envelope=envelope,
            handler=self.agent,
        )
        return {**state, "normalized_template": result.output.structured_output["template_text"]}

    def build_naming_plan(self, state: NamingPlanState) -> NamingPlanState:
        assignment = self.assignment_repo.get_by_public_id(state["assignment_public_id"])
        operations: list[dict[str, Any]] = []
        for submission in state["submissions"]:
            if submission.enrollment is None:
                continue
            suffix = Path(submission.current_path).suffix
            target_filename = state["normalized_template"].format(
                assignment=f"作业{assignment.seq_no}",
                student_no=submission.enrollment.display_student_no or "未知学号",
                name=submission.enrollment.display_name,
            )
            target_path = str(Path(submission.current_path).with_name(f"{target_filename}{suffix}"))
            operations.append(
                {
                    "submission_id": submission.id,
                    "source_path": submission.current_path,
                    "target_path": target_path,
                    "status": "planned",
                    "conflict_strategy": "skip_if_exists",
                    "command_preview": preview_rename_command(submission.current_path, target_path),
                }
            )
        state["operations"] = operations
        self.audit_service.record(
            event_type="naming_plan_built",
            object_type="assignment",
            object_public_id=assignment.public_id,
            payload={"operation_count": len(operations)},
        )
        return {**state, "operations": operations}
