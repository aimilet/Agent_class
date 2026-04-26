from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents import AssetSelectorAgent, GradingAgent, GradingValidatorAgent
from backend.agents.base import AgentExecutor
from backend.core.settings import get_settings
from backend.domain.models import AssetSelectionResult, ReviewItemResult, ReviewResult, ReviewRun, Submission
from backend.graphs.common import compile_graph
from backend.infra.llm import build_file_message_parts
from backend.infra.observability import AuditService
from backend.schemas.common import AgentInputEnvelope, AgentRunContext, AgentTaskContext
from backend.services.document_parser import DocumentParser
from backend.services.submission_bundle import SubmissionBundleParser


class SubmissionReviewGraphInput(TypedDict):
    review_run_public_id: str
    submission_public_id: str
    operator_id: str


class SubmissionReviewState(SubmissionReviewGraphInput, total=False):
    selected_assets: list[dict[str, Any]]
    ignored_assets: list[dict[str, Any]]
    submission_text: str
    grading_output: dict[str, Any]
    validation_output: dict[str, Any]


class SubmissionReviewGraph:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit_service = AuditService(session)
        self.selector_agent = AssetSelectorAgent()
        self.grading_agent = GradingAgent()
        self.validator_agent = GradingValidatorAgent()
        self.executor = AgentExecutor(session)
        self.parser = DocumentParser()
        self.settings = get_settings()
        self.bundle_parser = SubmissionBundleParser(self.parser, self.settings)
        self.compiled = compile_graph(
            state_schema=SubmissionReviewState,
            input_schema=SubmissionReviewGraphInput,
            output_schema=SubmissionReviewState,
            name="submission_review_graph",
            nodes=[
                ("select_assets", self.select_assets),
                ("parse_assets", self.parse_assets),
                ("grade_submission", self.grade_submission),
                ("persist_result", self.persist_result),
            ],
            edges=[
                ("select_assets", "parse_assets"),
                ("parse_assets", "grade_submission"),
                ("grade_submission", "persist_result"),
            ],
        )

    def invoke(self, *, review_run_public_id: str, submission_public_id: str, operator_id: str = "system") -> dict[str, Any]:
        state: SubmissionReviewGraphInput = {
            "review_run_public_id": review_run_public_id,
            "submission_public_id": submission_public_id,
            "operator_id": operator_id,
        }
        if self.compiled is not None:
            return self.compiled.invoke(state)
        fallback_state: SubmissionReviewState = dict(state)
        for node in (self.select_assets, self.parse_assets, self.grade_submission, self.persist_result):
            fallback_state = node(fallback_state)
        return fallback_state

    def select_assets(self, state: SubmissionReviewState) -> SubmissionReviewState:
        review_run = self.session.scalar(select(ReviewRun).where(ReviewRun.public_id == state["review_run_public_id"]))
        submission = self.session.scalar(select(Submission).where(Submission.public_id == state["submission_public_id"]))
        review_run.status = "selecting_assets"
        submission.status = "reviewing"
        self.session.flush()
        assets = [
            {
                "public_id": asset.public_id,
                "logical_path": asset.logical_path,
                "real_path": asset.real_path,
                "mime_type": asset.mime_type,
                "size_bytes": asset.size_bytes,
            }
            for asset in submission.assets
        ]
        result = self.executor.run(
            graph_name="submission_review_graph",
            stage_name="asset_selector_agent",
            agent_name=self.selector_agent.name,
            prompt_version=self.selector_agent.prompt_version,
            model_name=self.selector_agent.model_name,
            envelope=AgentInputEnvelope(
                run_context=AgentRunContext(
                    graph_name="submission_review_graph",
                    stage_name="asset_selector_agent",
                    run_id=f"submission_review:{review_run.public_id}:{submission.public_id}",
                    assignment_id=review_run.assignment.public_id,
                    review_prep_id=review_run.review_prep.public_id,
                    submission_id=submission.public_id,
                    prompt_version=self.selector_agent.prompt_version,
                    model_name=self.selector_agent.model_name,
                ),
                task_context=AgentTaskContext(now=datetime.now(), operator_id=state["operator_id"]),
                payload={"assets": assets},
            ),
            handler=self.selector_agent,
        )
        selected_assets = result.output.structured_output.get("selected_assets", [])
        ignored_assets = result.output.structured_output.get("ignored_assets", [])
        self.session.add(
            AssetSelectionResult(
                public_id=AssetSelectionResult.build_public_id(),
                review_run_id=review_run.id,
                submission_id=submission.id,
                selected_assets_json=selected_assets,
                ignored_assets_json=ignored_assets,
                summary=result.output.summary,
            )
        )
        self.session.flush()
        return {**state, "selected_assets": selected_assets, "ignored_assets": ignored_assets}

    def parse_assets(self, state: SubmissionReviewState) -> SubmissionReviewState:
        texts: list[str] = []
        for asset in state["selected_assets"][: self.settings.vision_max_assets_per_submission]:
            if not asset.get("real_path"):
                continue
            if build_file_message_parts([asset], path_key="real_path", filename_key="logical_path", image_limit=1):
                continue
            try:
                parsed = self.parser.parse(asset["real_path"])
                if parsed.text.strip():
                    texts.append(parsed.text.strip())
            except Exception:
                try:
                    bundle = self.bundle_parser.parse_submission(asset["real_path"])
                except Exception:
                    continue
                if bundle.text.strip():
                    texts.append(bundle.text.strip())
        return {**state, "submission_text": "\n\n".join(texts)}

    def grade_submission(self, state: SubmissionReviewState) -> SubmissionReviewState:
        review_run = self.session.scalar(select(ReviewRun).where(ReviewRun.public_id == state["review_run_public_id"]))
        submission = self.session.scalar(select(Submission).where(Submission.public_id == state["submission_public_id"]))
        review_run.status = "grading"
        self.session.flush()
        reference_text = "\n\n".join(
            item.reference_answer_full or item.reference_answer_short or item.question_full_text
            for item in review_run.review_prep.question_items
        )
        grading_output = self.executor.run(
            graph_name="submission_review_graph",
            stage_name="grading_agent",
            agent_name=self.grading_agent.name,
            prompt_version=self.grading_agent.prompt_version,
            model_name=self.grading_agent.model_name,
            envelope=AgentInputEnvelope(
                run_context=AgentRunContext(
                    graph_name="submission_review_graph",
                    stage_name="grading_agent",
                    run_id=f"submission_review:{review_run.public_id}:{submission.public_id}:grading",
                    assignment_id=review_run.assignment.public_id,
                    review_prep_id=review_run.review_prep.public_id,
                    submission_id=submission.public_id,
                    prompt_version=self.grading_agent.prompt_version,
                    model_name=self.grading_agent.model_name,
                ),
                task_context=AgentTaskContext(now=datetime.now(), operator_id=state["operator_id"]),
                payload={
                    "submission_text": state["submission_text"],
                    "reference_text": reference_text,
                    "score_scale": self.settings.default_review_scale,
                    "selected_assets": state["selected_assets"],
                },
            ),
            handler=self.grading_agent,
        ).output
        validation_output = self.executor.run(
            graph_name="submission_review_graph",
            stage_name="grading_validator_agent",
            agent_name=self.validator_agent.name,
            prompt_version=self.validator_agent.prompt_version,
            model_name=self.validator_agent.model_name,
            envelope=AgentInputEnvelope(
                run_context=AgentRunContext(
                    graph_name="submission_review_graph",
                    stage_name="grading_validator_agent",
                    run_id=f"submission_review:{review_run.public_id}:{submission.public_id}:validator",
                    assignment_id=review_run.assignment.public_id,
                    review_prep_id=review_run.review_prep.public_id,
                    submission_id=submission.public_id,
                    prompt_version=self.validator_agent.prompt_version,
                    model_name=self.validator_agent.model_name,
                ),
                task_context=AgentTaskContext(now=datetime.now(), operator_id=state["operator_id"]),
                payload={
                    **grading_output.structured_output,
                    "confidence": grading_output.confidence,
                },
            ),
            handler=self.validator_agent,
        ).output
        return {
            **state,
            "grading_output": grading_output.structured_output,
            "validation_output": validation_output.structured_output,
        }

    def persist_result(self, state: SubmissionReviewState) -> SubmissionReviewState:
        review_run = self.session.scalar(select(ReviewRun).where(ReviewRun.public_id == state["review_run_public_id"]))
        submission = self.session.scalar(select(Submission).where(Submission.public_id == state["submission_public_id"]))
        review_run.status = "validating"
        self.session.flush()
        result = ReviewResult(
            public_id=ReviewResult.build_public_id(),
            review_run_id=review_run.id,
            submission_id=submission.id,
            total_score=state["grading_output"]["total_score"],
            score_scale=state["grading_output"]["score_scale"],
            summary=state["grading_output"]["summary"],
            decision=state["grading_output"]["decision"],
            confidence=state["grading_output"].get("confidence"),
            status="validated" if state["validation_output"]["status"] == "validated" else "needs_manual_review",
            result_json=state["grading_output"],
        )
        self.session.add(result)
        self.session.flush()
        question_items = review_run.review_prep.question_items
        per_item_score = result.total_score / max(len(question_items), 1)
        for item in question_items:
            self.session.add(
                ReviewItemResult(
                    public_id=ReviewItemResult.build_public_id(),
                    review_result_id=result.id,
                    question_item_id=item.id,
                    score=per_item_score,
                    reason=result.summary,
                    evidence_json={"selected_assets": [asset["logical_path"] for asset in state["selected_assets"]]},
                )
            )
        submission.status = "reviewed" if result.status == "validated" else "review_ready"
        self.audit_service.record(
            event_type="submission_review_completed",
            object_type="submission",
            object_public_id=submission.public_id,
            payload={"review_result_public_id": result.public_id, "status": result.status},
        )
        self.session.flush()
        return {**state}
