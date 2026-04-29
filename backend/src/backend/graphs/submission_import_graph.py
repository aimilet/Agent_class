from __future__ import annotations

import tarfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from backend.agents import SubmissionMatchAgent
from backend.agents.base import AgentExecutor
from backend.core.background_jobs import get_background_job_registry
from backend.core.ids import generate_public_id
from backend.core.pathing import resolve_user_path
from backend.core.runtime_review_settings import RuntimeReviewSettingsStore
from backend.core.settings import get_settings
from backend.db.repositories import AssignmentRepository, CourseRepository, EnrollmentRepository, SubmissionRepository
from backend.domain.models import Assignment
from backend.domain.state_machine import ensure_transition
from backend.graphs.common import compile_graph
from backend.infra.observability import AuditService
from backend.infra.storage import mime_type_for_path, sha256_for_file
from backend.schemas.common import AgentInputEnvelope, AgentRunContext, AgentTaskContext


ARCHIVE_SUFFIXES = {".zip", ".tar", ".tgz", ".tbz", ".tbz2", ".txz", ".gz", ".bz2", ".xz"}
SKIPPED_ARCHIVE_PARTS = {
    "__MACOSX",
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    "dist",
    "build",
    "target",
}
SKIPPED_ARCHIVE_FILENAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


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
        self.settings = get_settings()
        self.runtime_settings = RuntimeReviewSettingsStore(self.settings).load()
        self.job_registry = get_background_job_registry()
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

    def _raise_if_cancel_requested(self, batch_public_id: str) -> None:
        self.job_registry.raise_if_cancel_requested("submission_import_batch", batch_public_id)

    def _list_root_entries(self, assignment: Assignment, root_path: Path, *, batch_public_id: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for child in sorted(root_path.iterdir(), key=lambda item: item.name):
            self._raise_if_cancel_requested(batch_public_id)
            if child.name.startswith("."):
                continue
            entries.append(
                {
                    "assignment_public_id": assignment.public_id,
                    "source_entry_name": child.name,
                    "source_entry_path": str(child.resolve()),
                    "assets": self._build_asset_manifest(child, batch_public_id=batch_public_id),
                }
            )
        return entries

    def _build_asset_manifest(self, entry: Path, *, batch_public_id: str) -> list[dict[str, Any]]:
        counter = {"files": 0}
        unpack_root = self.settings.artifacts_root / "submission_unpacked" / generate_public_id("unpack")
        logical_path = entry.name if entry.is_file() else ""
        assets = self._collect_asset_manifest(
            entry,
            logical_path=logical_path,
            unpack_root=unpack_root,
            depth=0,
            counter=counter,
            batch_public_id=batch_public_id,
        )
        if assets:
            return assets
        if entry.is_file():
            return [self._single_asset(entry, logical_path=entry.name, asset_role="archive_unexpanded" if self._is_archive(entry) else None)]
        return []

    def _collect_asset_manifest(
        self,
        path: Path,
        *,
        logical_path: str,
        unpack_root: Path,
        depth: int,
        counter: dict[str, int],
        batch_public_id: str,
    ) -> list[dict[str, Any]]:
        self._raise_if_cancel_requested(batch_public_id)
        if self._should_skip_path(path):
            return []
        if depth > self.runtime_settings.submission_unpack_max_depth:
            return []
        if path.is_dir():
            assets: list[dict[str, Any]] = []
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                self._raise_if_cancel_requested(batch_public_id)
                child_logical = f"{logical_path}/{child.name}" if logical_path else child.name
                assets.extend(
                    self._collect_asset_manifest(
                        child,
                        logical_path=child_logical,
                        unpack_root=unpack_root,
                        depth=depth + 1,
                        counter=counter,
                        batch_public_id=batch_public_id,
                    )
                )
            return assets
        if not path.is_file():
            return []
        if self._is_archive(path):
            if depth >= self.runtime_settings.submission_unpack_max_depth:
                return [self._single_asset(path, logical_path=logical_path, asset_role="archive_unexpanded")]
            try:
                extract_root = self._extract_archive_for_manifest(path, unpack_root, batch_public_id=batch_public_id)
            except ValueError:
                return [self._single_asset(path, logical_path=logical_path, asset_role="archive_unexpanded")]
            assets: list[dict[str, Any]] = []
            for child in sorted(extract_root.iterdir(), key=lambda item: item.name):
                self._raise_if_cancel_requested(batch_public_id)
                child_logical = f"{logical_path}/{child.name}" if logical_path else child.name
                assets.extend(
                    self._collect_asset_manifest(
                        child,
                        logical_path=child_logical,
                        unpack_root=unpack_root,
                        depth=depth + 1,
                        counter=counter,
                        batch_public_id=batch_public_id,
                    )
                )
            return assets
        counter["files"] += 1
        if counter["files"] > self.runtime_settings.submission_unpack_max_files:
            return []
        return [self._single_asset(path, logical_path=logical_path)]

    def _single_asset(self, path: Path, *, logical_path: str, asset_role: str | None = None) -> dict[str, Any]:
        return {
            "logical_path": logical_path,
            "real_path": str(path.resolve()),
            "file_hash": sha256_for_file(path),
            "mime_type": mime_type_for_path(path),
            "size_bytes": path.stat().st_size,
            "asset_role": asset_role,
        }

    def _is_archive(self, path: Path) -> bool:
        suffix = path.suffix.lower()
        return suffix in ARCHIVE_SUFFIXES

    def _should_skip_path(self, path: Path) -> bool:
        return path.name in SKIPPED_ARCHIVE_PARTS or path.name in SKIPPED_ARCHIVE_FILENAMES or path.name.startswith(".")

    def _should_skip_archive_member(self, name: str) -> bool:
        parts = [part for part in Path(name.replace("\\", "/")).parts if part not in {"", "."}]
        if not parts:
            return True
        return bool(set(parts) & SKIPPED_ARCHIVE_PARTS) or parts[-1] in SKIPPED_ARCHIVE_FILENAMES or parts[-1].startswith(".")

    def _extract_archive_for_manifest(self, archive_path: Path, unpack_root: Path, *, batch_public_id: str) -> Path:
        self._raise_if_cancel_requested(batch_public_id)
        extract_root = unpack_root / generate_public_id("archive")
        extract_root.mkdir(parents=True, exist_ok=True)
        if zipfile.is_zipfile(archive_path):
            self._extract_zip_for_manifest(archive_path, extract_root, batch_public_id=batch_public_id)
            return extract_root
        if tarfile.is_tarfile(archive_path):
            self._extract_tar_for_manifest(archive_path, extract_root, batch_public_id=batch_public_id)
            return extract_root
        raise ValueError(f"无法识别压缩格式：{archive_path.name}")

    def _safe_extract_target(self, extract_root: Path, member_name: str) -> Path | None:
        if self._should_skip_archive_member(member_name):
            return None
        root_resolved = extract_root.resolve()
        target = (extract_root / member_name.replace("\\", "/")).resolve()
        if root_resolved not in target.parents and target != root_resolved:
            return None
        return target

    def _extract_zip_for_manifest(self, archive_path: Path, extract_root: Path, *, batch_public_id: str) -> None:
        extracted = 0
        with zipfile.ZipFile(archive_path) as handle:
            for member in handle.infolist():
                self._raise_if_cancel_requested(batch_public_id)
                target = self._safe_extract_target(extract_root, member.filename)
                if target is None:
                    continue
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                extracted += 1
                if extracted > self.runtime_settings.submission_unpack_max_files:
                    raise ValueError(f"压缩包文件数超过上限 {self.runtime_settings.submission_unpack_max_files}。")
                target.parent.mkdir(parents=True, exist_ok=True)
                with handle.open(member) as source, target.open("wb") as sink:
                    sink.write(source.read())

    def _extract_tar_for_manifest(self, archive_path: Path, extract_root: Path, *, batch_public_id: str) -> None:
        extracted = 0
        with tarfile.open(archive_path) as handle:
            for member in handle.getmembers():
                self._raise_if_cancel_requested(batch_public_id)
                target = self._safe_extract_target(extract_root, member.name)
                if target is None:
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                extracted += 1
                if extracted > self.runtime_settings.submission_unpack_max_files:
                    raise ValueError(f"压缩包文件数超过上限 {self.runtime_settings.submission_unpack_max_files}。")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = handle.extractfile(member)
                if source is None:
                    continue
                with source, target.open("wb") as sink:
                    sink.write(source.read())

    def scan_submission_root(self, state: SubmissionImportState) -> SubmissionImportState:
        self._raise_if_cancel_requested(state["batch_public_id"])
        batch = self.submission_repo.get_import_batch(state["batch_public_id"])
        assignment = self.assignment_repo.get_by_public_id(state["assignment_public_id"])
        ensure_transition("submission_import_batch", batch.status, "scanning")
        batch.status = "scanning"
        self.session.flush()
        root_path = resolve_user_path(batch.root_path, settings=self.settings)
        batch.root_path = str(root_path)
        if not root_path.exists() or not root_path.is_dir():
            batch.status = "failed"
            batch.error_message = "作业根目录不存在，或不是目录。"
            self.session.flush()
            raise ValueError(batch.error_message)
        entry_manifest = self._list_root_entries(assignment, root_path, batch_public_id=batch.public_id)
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
        self._raise_if_cancel_requested(state["batch_public_id"])
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
        self._raise_if_cancel_requested(state["batch_public_id"])
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
        self._raise_if_cancel_requested(state["batch_public_id"])
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
