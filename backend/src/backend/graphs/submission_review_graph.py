from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents import AssetSelectorAgent, GradingAgent, GradingValidatorAgent
from backend.agents.base import AgentExecutor
from backend.core.background_jobs import BackgroundJobCancelled, get_background_job_registry
from backend.core.ids import generate_public_id
from backend.core.runtime_review_settings import RuntimeReviewSettingsStore
from backend.core.settings import get_settings
from backend.domain.models import AssetSelectionResult, ReviewItemResult, ReviewResult, ReviewRun, Submission
from backend.graphs.common import compile_graph
from backend.infra.observability import AuditService
from backend.schemas.common import AgentInputEnvelope, AgentRunContext, AgentTaskContext
from backend.services.document_parser import LEGACY_PRESENTATION_SUFFIXES, PRESENTATION_SUFFIXES, DocumentParser, VisualAsset
from backend.services.submission_bundle import SubmissionBundleParser


REVIEW_EXTRACTION_SUFFIXES = {".docx", ".pdf", *PRESENTATION_SUFFIXES, *LEGACY_PRESENTATION_SUFFIXES}


class SubmissionReviewGraphInput(TypedDict):
    review_run_public_id: str
    submission_public_id: str
    operator_id: str


class SubmissionReviewState(SubmissionReviewGraphInput, total=False):
    selected_assets: list[dict[str, Any]]
    ignored_assets: list[dict[str, Any]]
    submission_text: str
    extracted_visual_assets: list[dict[str, Any]]
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
        self.runtime_settings_store = RuntimeReviewSettingsStore(self.settings)
        self.bundle_parser = SubmissionBundleParser(self.parser, self.settings)
        self.job_registry = get_background_job_registry()
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
        try:
            if self.compiled is not None:
                return self.compiled.invoke(state)
            fallback_state: SubmissionReviewState = dict(state)
            for node in (self.select_assets, self.parse_assets, self.grade_submission, self.persist_result):
                fallback_state = node(fallback_state)
            return fallback_state
        except BackgroundJobCancelled:
            raise
        except Exception as exc:
            return self.mark_submission_for_manual_review(
                state=state,
                error_message=f"{type(exc).__name__}: {exc}",
                reason="submission_review_graph_failed",
            )

    def _raise_if_cancel_requested(self, review_run_public_id: str) -> None:
        self.job_registry.raise_if_cancel_requested("review_run", review_run_public_id)

    def select_assets(self, state: SubmissionReviewState) -> SubmissionReviewState:
        self._raise_if_cancel_requested(state["review_run_public_id"])
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
        extracted_visual_assets: list[dict[str, Any]] = []
        runtime_settings = self.runtime_settings_store.load()
        vision_limit = runtime_settings.vision_max_assets_per_submission
        for asset in state["selected_assets"][:vision_limit]:
            self._raise_if_cancel_requested(state["review_run_public_id"])
            if len(extracted_visual_assets) >= vision_limit:
                break
            raw_path = asset.get("real_path")
            if not raw_path:
                continue
            path = Path(raw_path).expanduser().resolve()
            if path.suffix.lower() not in REVIEW_EXTRACTION_SUFFIXES:
                continue
            try:
                parsed = self.parser.parse(path, include_ocr=False)
                if parsed.text.strip():
                    texts.append(self._format_parsed_text(asset=asset, text=parsed.text))
                extracted_visual_assets.extend(
                    self._persist_visual_assets(
                        review_run_public_id=state["review_run_public_id"],
                        submission_public_id=state["submission_public_id"],
                        source_asset=asset,
                        visual_assets=parsed.visual_assets,
                        remaining_slots=vision_limit - len(extracted_visual_assets),
                    )
                )
            except Exception:
                try:
                    bundle = self.bundle_parser.parse_submission(path)
                except Exception:
                    continue
                if bundle.text.strip():
                    texts.append(self._format_parsed_text(asset=asset, text=bundle.text))
                extracted_visual_assets.extend(
                    self._persist_visual_assets(
                        review_run_public_id=state["review_run_public_id"],
                        submission_public_id=state["submission_public_id"],
                        source_asset=asset,
                        visual_assets=bundle.visual_assets,
                        remaining_slots=vision_limit - len(extracted_visual_assets),
                    )
                )
        return {
            **state,
            "submission_text": "\n\n".join(texts),
            "extracted_visual_assets": extracted_visual_assets,
        }

    def grade_submission(self, state: SubmissionReviewState) -> SubmissionReviewState:
        self._raise_if_cancel_requested(state["review_run_public_id"])
        review_run = self.session.scalar(select(ReviewRun).where(ReviewRun.public_id == state["review_run_public_id"]))
        submission = self.session.scalar(select(Submission).where(Submission.public_id == state["submission_public_id"]))
        runtime_settings = self.runtime_settings_store.load()
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
                    "submission_text": state.get("submission_text", ""),
                    "reference_text": reference_text,
                    "score_scale": runtime_settings.default_review_scale,
                    "selected_assets": state["selected_assets"],
                    "extracted_visual_assets": state.get("extracted_visual_assets", []),
                    "vision_max_assets_per_submission": runtime_settings.vision_max_assets_per_submission,
                },
            ),
            handler=self.grading_agent,
        ).output
        self._raise_if_cancel_requested(state["review_run_public_id"])
        if runtime_settings.review_run_enable_validation_agent:
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
            validation_structured_output = validation_output.structured_output
        else:
            validation_structured_output = {
                "status": "validated",
                "errors": [],
                "validation_skipped": True,
            }
        return {
            **state,
            "grading_output": grading_output.structured_output,
            "validation_output": validation_structured_output,
        }

    def _format_parsed_text(self, *, asset: dict[str, Any], text: str) -> str:
        display_name = asset.get("logical_path") or asset.get("real_path") or "未命名文件"
        return f"[提取正文] {display_name}\n{text.strip()}"

    def _persist_visual_assets(
        self,
        *,
        review_run_public_id: str,
        submission_public_id: str,
        source_asset: dict[str, Any],
        visual_assets: list[VisualAsset],
        remaining_slots: int,
    ) -> list[dict[str, Any]]:
        if not visual_assets or remaining_slots <= 0:
            return []

        source_name = str(source_asset.get("logical_path") or source_asset.get("real_path") or "source")
        target_root = (
            self.settings.artifacts_root
            / "review_visual_assets"
            / review_run_public_id
            / submission_public_id
            / (source_asset.get("public_id") or generate_public_id("asset"))
        )
        target_root.mkdir(parents=True, exist_ok=True)

        persisted_assets: list[dict[str, Any]] = []
        for index, visual_asset in enumerate(visual_assets[:remaining_slots], start=1):
            suffix = Path(visual_asset.origin).suffix or self._guess_suffix_from_mime(visual_asset.mime_type)
            stored_path = target_root / f"{index:02d}_{generate_public_id('img')}{suffix}"
            stored_path.write_bytes(visual_asset.data)
            persisted_assets.append(
                {
                    "logical_path": f"{source_name} / 内嵌图片 {index} ({Path(visual_asset.origin).name or 'image'})",
                    "real_path": str(stored_path),
                    "mime_type": visual_asset.mime_type,
                    "size_bytes": len(visual_asset.data),
                    "derived_from_asset_public_id": source_asset.get("public_id"),
                    "derived_from_logical_path": source_name,
                }
            )
        return persisted_assets

    def _guess_suffix_from_mime(self, mime_type: str | None) -> str:
        if mime_type == "image/jpeg":
            return ".jpg"
        if mime_type == "image/webp":
            return ".webp"
        if mime_type == "image/bmp":
            return ".bmp"
        if mime_type == "image/tiff":
            return ".tiff"
        return ".png"

    def mark_submission_for_manual_review(
        self,
        *,
        state: SubmissionReviewGraphInput | SubmissionReviewState,
        error_message: str,
        reason: str,
    ) -> SubmissionReviewState:
        review_run = self.session.scalar(select(ReviewRun).where(ReviewRun.public_id == state["review_run_public_id"]))
        submission = self.session.scalar(select(Submission).where(Submission.public_id == state["submission_public_id"]))
        if review_run is None or submission is None:
            raise ValueError("评审运行或作业提交不存在，无法写入人工复核结果。")
        selected_assets = state.get("selected_assets", [])
        summary = f"评审输出异常，已转人工复核：{error_message}"
        grading_output = {
            "total_score": 0.0,
            "score_scale": self.runtime_settings_store.load().default_review_scale,
            "summary": summary,
            "decision": "needs_manual_review",
            "confidence": 0.0,
            "item_results": [],
            "fallback_reason": reason,
            "error_message": error_message,
        }
        validation_output = {
            "status": "needs_manual_review",
            "errors": [error_message],
        }
        result = self.session.scalar(
            select(ReviewResult).where(
                ReviewResult.review_run_id == review_run.id,
                ReviewResult.submission_id == submission.id,
            )
        )
        if result is None:
            result = ReviewResult(
                public_id=ReviewResult.build_public_id(),
                review_run_id=review_run.id,
                submission_id=submission.id,
            )
            self.session.add(result)
            self.session.flush()
        result.total_score = grading_output["total_score"]
        result.score_scale = grading_output["score_scale"]
        result.summary = grading_output["summary"]
        result.decision = grading_output["decision"]
        result.confidence = grading_output["confidence"]
        result.status = "needs_manual_review"
        result.result_json = grading_output
        evidence_json = {
            "selected_assets": [asset["logical_path"] for asset in selected_assets if asset.get("logical_path")],
            "fallback_reason": reason,
            "error_message": error_message,
        }
        if result.item_results:
            for item_result in result.item_results:
                item_result.score = 0.0
                item_result.reason = summary
                item_result.evidence_json = evidence_json
        else:
            for item in review_run.review_prep.question_items:
                self.session.add(
                    ReviewItemResult(
                        public_id=ReviewItemResult.build_public_id(),
                        review_result_id=result.id,
                        question_item_id=item.id,
                        score=0.0,
                        reason=summary,
                        evidence_json=evidence_json,
                    )
                )
        review_run.status = "validating"
        submission.status = "review_ready"
        self.audit_service.record(
            event_type="submission_review_degraded_to_manual_review",
            object_type="submission",
            object_public_id=submission.public_id,
            payload={
                "review_run_public_id": review_run.public_id,
                "review_result_public_id": result.public_id,
                "reason": reason,
                "error_message": error_message,
            },
        )
        self.session.flush()
        return {
            **state,
            "grading_output": grading_output,
            "validation_output": validation_output,
        }

    def persist_result(self, state: SubmissionReviewState) -> SubmissionReviewState:
        self._raise_if_cancel_requested(state["review_run_public_id"])
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
