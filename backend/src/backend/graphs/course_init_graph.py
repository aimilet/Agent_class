from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from backend.agents import CourseInitAgent
from backend.agents.base import AgentExecutor
from backend.core.background_jobs import get_background_job_registry
from backend.core.errors import DomainError
from backend.db.repositories import CourseRepository, RosterRepository
from backend.domain.state_machine import ensure_transition
from backend.graphs.common import compile_graph
from backend.infra.observability import AuditService
from backend.schemas.common import AgentInputEnvelope, AgentRunContext, AgentTaskContext


class CourseInitGraphInput(TypedDict):
    course_public_id: str
    batch_public_id: str
    operator_id: str


class CourseInitState(CourseInitGraphInput, total=False):
    parse_mode: str
    material_manifest: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    review_required: bool
    warnings: list[str]
    summary: dict[str, Any]


class CourseInitGraph:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.course_repo = CourseRepository(session)
        self.roster_repo = RosterRepository(session)
        self.audit_service = AuditService(session)
        self.agent = CourseInitAgent()
        self.agent_executor = AgentExecutor(session)
        self.job_registry = get_background_job_registry()
        self.compiled = compile_graph(
            state_schema=CourseInitState,
            input_schema=CourseInitGraphInput,
            output_schema=CourseInitState,
            name="course_init_graph",
            nodes=[
                ("load_material_manifest", self.load_material_manifest),
                ("run_agent", self.run_agent),
                ("persist_candidates", self.persist_candidates),
                ("finalize_batch", self.finalize_batch),
            ],
            edges=[
                ("load_material_manifest", "run_agent"),
                ("run_agent", "persist_candidates"),
                ("persist_candidates", "finalize_batch"),
            ],
        )

    def invoke(self, *, course_public_id: str, batch_public_id: str, operator_id: str = "system") -> dict[str, Any]:
        state: CourseInitGraphInput = {
            "course_public_id": course_public_id,
            "batch_public_id": batch_public_id,
            "operator_id": operator_id,
        }
        if self.compiled is not None:
            return self.compiled.invoke(state)
        fallback_state: CourseInitState = {**state, "warnings": [], "summary": {"operator_id": operator_id}}
        for node in (self.load_material_manifest, self.run_agent, self.persist_candidates, self.finalize_batch):
            fallback_state = node(fallback_state)
        return fallback_state

    def _raise_if_cancel_requested(self, state: CourseInitState) -> None:
        self.job_registry.raise_if_cancel_requested("roster_import_batch", state["batch_public_id"])

    def load_material_manifest(self, state: CourseInitState) -> CourseInitState:
        self._raise_if_cancel_requested(state)
        course = self.course_repo.get_by_public_id(state["course_public_id"])
        batch = self.roster_repo.get_batch(state["batch_public_id"])
        ensure_transition("course", course.status, "initializing")
        ensure_transition("roster_import_batch", batch.status, "queued")
        course.status = "initializing"
        batch.status = "queued"
        self.session.flush()
        batch.status = "parsing"
        self.session.flush()
        self.audit_service.record(
            event_type="roster_import_started",
            object_type="roster_import_batch",
            object_public_id=batch.public_id,
            payload={"course_public_id": course.public_id},
        )
        return {
            **state,
            "parse_mode": batch.parse_mode,
            "material_manifest": [{"filename": item["original_name"], "path": item["path"]} for item in batch.source_files_json],
            "warnings": state.get("warnings", []),
            "summary": state.get("summary", {"operator_id": state["operator_id"]}),
        }

    def run_agent(self, state: CourseInitState) -> CourseInitState:
        self._raise_if_cancel_requested(state)
        course = self.course_repo.get_by_public_id(state["course_public_id"])
        envelope = AgentInputEnvelope(
            run_context=AgentRunContext(
                graph_name="course_init_graph",
                stage_name="course_init_agent_extract",
                run_id=f"course_init:{state['batch_public_id']}",
                course_id=course.public_id,
                prompt_version=self.agent.prompt_version,
                model_name=self.agent.model_name,
            ),
            task_context=AgentTaskContext(now=datetime.now(), operator_id=state["operator_id"]),
            payload={
                "course_meta": {
                    "course_name": course.course_name,
                    "term": course.term,
                    "class_label": course.class_label,
                },
                "material_manifest": state["material_manifest"],
                "parse_mode": state["parse_mode"],
            },
        )
        result = self.agent_executor.run(
            graph_name="course_init_graph",
            stage_name="course_init_agent_extract",
            agent_name=self.agent.name,
            prompt_version=self.agent.prompt_version,
            model_name=self.agent.model_name,
            envelope=envelope,
            handler=self.agent,
        )
        return {
            **state,
            "candidates": result.output.structured_output.get("students", []),
            "warnings": result.output.warnings,
            "review_required": result.output.needs_review,
            "summary": {**state.get("summary", {}), "agent_run_public_id": result.run_public_id},
        }

    def persist_candidates(self, state: CourseInitState) -> CourseInitState:
        self._raise_if_cancel_requested(state)
        batch = self.roster_repo.get_batch(state["batch_public_id"])
        candidates = self.roster_repo.replace_candidates(
            batch,
            [
                {
                    **candidate,
                    "decision_status": "pending",
                }
                for candidate in state["candidates"]
            ],
        )
        batch.summary_json = {
            "candidate_count": len(candidates),
            "warnings": state["warnings"],
        }
        batch.status = "needs_review" if state["review_required"] else "parsed"
        if not candidates:
            batch.status = "failed"
            batch.error_message = "未能识别出任何学生名单候选。"
        self.session.flush()
        return {**state}

    def finalize_batch(self, state: CourseInitState) -> CourseInitState:
        self._raise_if_cancel_requested(state)
        batch = self.roster_repo.get_batch(state["batch_public_id"])
        self.audit_service.record(
            event_type="roster_import_parsed",
            object_type="roster_import_batch",
            object_public_id=batch.public_id,
            payload={"status": batch.status, "summary": batch.summary_json},
        )
        if batch.status == "failed":
            course = self.course_repo.get_by_public_id(state["course_public_id"])
            course.status = "failed"
            course.last_error = batch.error_message
            self.session.flush()
            raise DomainError(batch.error_message or "名单解析失败。", code="roster_import_failed", status_code=400)
        return {**state}
