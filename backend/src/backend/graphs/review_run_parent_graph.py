from __future__ import annotations

from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.background_jobs import BackgroundJobCancelled, get_background_job_registry
from backend.domain.models import ReviewRun, Submission
from backend.graphs.common import compile_graph
from backend.graphs.submission_review_graph import SubmissionReviewGraph
from backend.infra.observability import AuditService


class ReviewRunParentGraphInput(TypedDict):
    review_run_public_id: str
    operator_id: str


class ReviewRunParentState(ReviewRunParentGraphInput, total=False):
    submission_public_ids: list[str]
    completed_results: int
    manual_review_results: int


class ReviewRunParentGraph:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit_service = AuditService(session)
        self.child_graph = SubmissionReviewGraph(session)
        self.job_registry = get_background_job_registry()
        self.compiled = compile_graph(
            state_schema=ReviewRunParentState,
            input_schema=ReviewRunParentGraphInput,
            output_schema=ReviewRunParentState,
            name="review_run_parent_graph",
            nodes=[
                ("load_submission_scope", self.load_submission_scope),
                ("run_children", self.run_children),
                ("finalize_run", self.finalize_run),
            ],
            edges=[
                ("load_submission_scope", "run_children"),
                ("run_children", "finalize_run"),
            ],
        )

    def invoke(self, *, review_run_public_id: str, operator_id: str = "system") -> dict[str, Any]:
        state: ReviewRunParentGraphInput = {
            "review_run_public_id": review_run_public_id,
            "operator_id": operator_id,
        }
        if self.compiled is not None:
            return self.compiled.invoke(state)
        fallback_state: ReviewRunParentState = {
            **state,
            "completed_results": 0,
            "manual_review_results": 0,
        }
        for node in (self.load_submission_scope, self.run_children, self.finalize_run):
            fallback_state = node(fallback_state)
        return fallback_state

    def _raise_if_cancel_requested(self, review_run_public_id: str) -> None:
        self.job_registry.raise_if_cancel_requested("review_run", review_run_public_id)

    def load_submission_scope(self, state: ReviewRunParentState) -> ReviewRunParentState:
        self._raise_if_cancel_requested(state["review_run_public_id"])
        review_run = self.session.scalar(select(ReviewRun).where(ReviewRun.public_id == state["review_run_public_id"]))
        submissions = self.session.scalars(
            select(Submission)
            .where(
                Submission.assignment_id == review_run.assignment_id,
                Submission.status.in_(["review_ready", "named", "reviewed"]),
            )
            .order_by(Submission.created_at.asc())
        ).all()
        return {
            **state,
            "submission_public_ids": [submission.public_id for submission in submissions],
            "completed_results": 0,
            "manual_review_results": 0,
        }

    def run_children(self, state: ReviewRunParentState) -> ReviewRunParentState:
        self._raise_if_cancel_requested(state["review_run_public_id"])
        completed_results = state.get("completed_results", 0)
        manual_review_results = state.get("manual_review_results", 0)
        for submission_public_id in state.get("submission_public_ids", []):
            self._raise_if_cancel_requested(state["review_run_public_id"])
            try:
                child_state = self.child_graph.invoke(
                    review_run_public_id=state["review_run_public_id"],
                    submission_public_id=submission_public_id,
                    operator_id=state["operator_id"],
                )
            except BackgroundJobCancelled:
                raise
            except Exception as exc:
                self.audit_service.record(
                    event_type="review_run_child_failed",
                    object_type="submission",
                    object_public_id=submission_public_id,
                    payload={
                        "review_run_public_id": state["review_run_public_id"],
                        "error_message": f"{type(exc).__name__}: {exc}",
                    },
                )
                if hasattr(self.child_graph, "mark_submission_for_manual_review"):
                    self.child_graph.mark_submission_for_manual_review(
                        state={
                            "review_run_public_id": state["review_run_public_id"],
                            "submission_public_id": submission_public_id,
                            "operator_id": state["operator_id"],
                        },
                        error_message=f"{type(exc).__name__}: {exc}",
                        reason="review_run_parent_graph_child_failed",
                    )
                # 逐个提交评审结果，保证前端轮询能看到增量结果。
                self.session.commit()
                manual_review_results += 1
                continue
            if child_state.get("validation_output", {}).get("status") == "needs_manual_review":
                manual_review_results += 1
            else:
                completed_results += 1
            # 每个 submission 评审完成后立即提交，避免等整批结束后前端才看见结果。
            self.session.commit()
        return {
            **state,
            "completed_results": completed_results,
            "manual_review_results": manual_review_results,
        }

    def finalize_run(self, state: ReviewRunParentState) -> ReviewRunParentState:
        self._raise_if_cancel_requested(state["review_run_public_id"])
        review_run = self.session.scalar(select(ReviewRun).where(ReviewRun.public_id == state["review_run_public_id"]))
        validated = [result for result in review_run.results if result.status == "validated"]
        manual = [result for result in review_run.results if result.status == "needs_manual_review"]
        review_run.status = "completed" if not manual else "needs_review"
        review_run.summary_json = {
            "result_count": len(review_run.results),
            "validated_count": len(validated),
            "manual_review_count": len(manual),
        }
        self.audit_service.record(
            event_type="review_run_completed",
            object_type="review_run",
            object_public_id=review_run.public_id,
            payload=review_run.summary_json,
        )
        self.session.flush()
        return {**state}
