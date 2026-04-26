from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from backend.agents import SubmissionMatchAgent
from backend.agents.base import AgentExecutor
from backend.db.repositories import AssignmentRepository, CourseRepository, EnrollmentRepository, SubmissionRepository
from backend.domain.models import Assignment
from backend.domain.state_machine import ensure_transition
from backend.graphs.common import compile_graph
from backend.infra.observability import AuditService
from backend.infra.storage import mime_type_for_path, sha256_for_file
from backend.schemas.common import AgentInputEnvelope, AgentRunContext, AgentTaskContext


class SubmissionImportGraphInput(TypedDict):
    assignment_public_id: str
    batch_public_id: str
    operator_id: str


class SubmissionImportState(SubmissionImportGraphInput, total=False):
    entry_manifest: list[dict[str, Any]]
    enrollments: list[dict[str, Any]]
    submissions: list[dict[str, Any]]
    review_required: bool


class SubmissionImportGraph:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.assignment_repo = AssignmentRepository(session)
        self.submission_repo = SubmissionRepository(session)
        self.course_repo = CourseRepository(session)
        self.enrollment_repo = EnrollmentRepository(session)
        self.audit_service = AuditService(session)
        self.agent = SubmissionMatchAgent()
        self.agent_executor = AgentExecutor(session)
        self.compiled = compile_graph(
            state_schema=SubmissionImportState,
            input_schema=SubmissionImportGraphInput,
            output_schema=SubmissionImportState,
            name="submission_import_graph",
            nodes=[
                ("scan_submission_root", self.scan_submission_root),
                ("run_match_agent", self.run_match_agent),
                ("persist_submissions", self.persist_submissions),
                ("finalize_batch", self.finalize_batch),
            ],
            edges=[
                ("scan_submission_root", "run_match_agent"),
                ("run_match_agent", "persist_submissions"),
                ("persist_submissions", "finalize_batch"),
            ],
        )

    def invoke(self, *, assignment_public_id: str, batch_public_id: str, operator_id: str = "system") -> dict[str, Any]:
        state: SubmissionImportGraphInput = {
            "assignment_public_id": assignment_public_id,
            "batch_public_id": batch_public_id,
            "operator_id": operator_id,
        }
        if self.compiled is not None:
            return self.compiled.invoke(state)
        fallback_state: SubmissionImportState = dict(state)
        for node in (self.scan_submission_root, self.run_match_agent, self.persist_submissions, self.finalize_batch):
            fallback_state = node(fallback_state)
        return fallback_state

    def _list_root_entries(self, assignment: Assignment, root_path: Path) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for child in sorted(root_path.iterdir(), key=lambda item: item.name):
            if child.name.startswith("."):
                continue
            entries.append(
                {
                    "assignment_public_id": assignment.public_id,
                    "source_entry_name": child.name,
                    "source_entry_path": str(child.resolve()),
                    "assets": self._build_asset_manifest(child),
                }
            )
        return entries

    def _build_asset_manifest(self, entry: Path) -> list[dict[str, Any]]:
        if entry.is_file():
            return [
                {
                    "logical_path": entry.name,
                    "real_path": str(entry.resolve()),
                    "file_hash": sha256_for_file(entry),
                    "mime_type": mime_type_for_path(entry),
                    "size_bytes": entry.stat().st_size,
                }
            ]
        assets: list[dict[str, Any]] = []
        for child in sorted(entry.rglob("*")):
            if not child.is_file():
                continue
            assets.append(
                {
                    "logical_path": child.relative_to(entry).as_posix(),
                    "real_path": str(child.resolve()),
                    "file_hash": sha256_for_file(child),
                    "mime_type": mime_type_for_path(child),
                    "size_bytes": child.stat().st_size,
                }
            )
        return assets

    def scan_submission_root(self, state: SubmissionImportState) -> SubmissionImportState:
        batch = self.submission_repo.get_import_batch(state["batch_public_id"])
        assignment = self.assignment_repo.get_by_public_id(state["assignment_public_id"])
        ensure_transition("submission_import_batch", batch.status, "scanning")
        batch.status = "scanning"
        self.session.flush()
        root_path = Path(batch.root_path).expanduser().resolve()
        if not root_path.exists() or not root_path.is_dir():
            batch.status = "failed"
            batch.error_message = "作业根目录不存在，或不是目录。"
            self.session.flush()
            raise ValueError(batch.error_message)
        entry_manifest = self._list_root_entries(assignment, root_path)
        course = assignment.course
        enrollments = [
            {
                "public_id": enrollment.public_id,
                "display_student_no": enrollment.display_student_no,
                "display_name": enrollment.display_name,
            }
            for enrollment in self.enrollment_repo.list_by_course(course)
        ]
        return {**state, "entry_manifest": entry_manifest, "enrollments": enrollments}

    def run_match_agent(self, state: SubmissionImportState) -> SubmissionImportState:
        batch = self.submission_repo.get_import_batch(state["batch_public_id"])
        batch.status = "matching"
        self.session.flush()
        envelope = AgentInputEnvelope(
            run_context=AgentRunContext(
                graph_name="submission_import_graph",
                stage_name="submission_match_agent",
                run_id=f"submission_import:{batch.public_id}",
                assignment_id=state["assignment_public_id"],
                prompt_version=self.agent.prompt_version,
                model_name=self.agent.model_name,
            ),
            task_context=AgentTaskContext(now=datetime.now(), operator_id=state["operator_id"]),
            payload={
                "entry_manifest": state["entry_manifest"],
                "enrollments": state["enrollments"],
            },
        )
        result = self.agent_executor.run(
            graph_name="submission_import_graph",
            stage_name="submission_match_agent",
            agent_name=self.agent.name,
            prompt_version=self.agent.prompt_version,
            model_name=self.agent.model_name,
            envelope=envelope,
            handler=self.agent,
        )
        submissions: list[dict[str, Any]] = []
        for entry, matched in zip(state["entry_manifest"], result.output.structured_output.get("submissions", []), strict=False):
            candidate_map = {item["public_id"]: item for item in state["enrollments"]}
            valid_candidates = [
                candidate for candidate in matched["match_candidates"] if candidate["enrollment_public_id"] in candidate_map
            ]
            best_public_id = valid_candidates[0]["enrollment_public_id"] if valid_candidates else None
            best_enrollment = candidate_map.get(best_public_id) if best_public_id else None
            submissions.append(
                {
                    **matched,
                    "enrollment_id": None,
                    "source_entry_name": entry["source_entry_name"],
                    "source_entry_path": entry["source_entry_path"],
                    "assets": entry["assets"],
                    "match_candidates": [
                        {
                            "enrollment_id": self.enrollment_repo.get_by_public_id(candidate["enrollment_public_id"]).id,
                            "confidence": candidate["confidence"],
                            "reason": candidate.get("reason"),
                            "rank_order": candidate["rank_order"],
                        }
                        for candidate in valid_candidates
                    ],
                    "status": matched["status"] if valid_candidates or matched["status"] == "unmatched" else "unmatched",
                    "matched_by": matched.get("matched_by"),
                    "match_confidence": matched.get("match_confidence"),
                    "match_reason": matched.get("match_reason"),
                    "enrollment_id": self.enrollment_repo.get_by_public_id(best_public_id).id if best_public_id and matched["status"] == "matched" else None,
                    "canonical_name": best_enrollment["display_name"] if best_enrollment else matched["canonical_name"],
                    "current_path": entry["source_entry_path"],
                }
            )
        return {**state, "submissions": submissions, "review_required": result.output.needs_review}

    def persist_submissions(self, state: SubmissionImportState) -> SubmissionImportState:
        batch = self.submission_repo.get_import_batch(state["batch_public_id"])
        created = self.submission_repo.replace_submissions(batch, state["submissions"])
        batch.summary_json = {
            "submission_count": len(created),
            "matched_count": sum(1 for item in state["submissions"] if item["status"] == "matched"),
        }
        batch.status = "needs_review" if state["review_required"] else "confirmed"
        self.session.flush()
        return {**state}

    def finalize_batch(self, state: SubmissionImportState) -> SubmissionImportState:
        batch = self.submission_repo.get_import_batch(state["batch_public_id"])
        assignment = self.assignment_repo.get_by_public_id(state["assignment_public_id"])
        if batch.status == "confirmed":
            assignment.status = "submissions_imported"
        self.audit_service.record(
            event_type="submission_import_completed",
            object_type="submission_import_batch",
            object_public_id=batch.public_id,
            payload={"status": batch.status, "summary": batch.summary_json},
        )
        self.session.flush()
        return {**state}
