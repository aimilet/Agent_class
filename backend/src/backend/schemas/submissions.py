from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import TimestampedPublicRead


class SubmissionImportBatchCreate(BaseModel):
    root_path: str


class SubmissionImportBatchRead(TimestampedPublicRead):
    assignment_public_id: str
    root_path: str
    status: str
    summary: dict[str, Any] | None = None
    error_message: str | None = None


class SubmissionAssetRead(TimestampedPublicRead):
    submission_public_id: str
    logical_path: str
    real_path: str
    file_hash: str | None
    mime_type: str | None
    size_bytes: int
    asset_role: str | None
    selected_by_agent: bool
    selected_reason: str | None
    is_ignored: bool


class SubmissionMatchCandidateRead(TimestampedPublicRead):
    submission_public_id: str
    enrollment_public_id: str
    confidence: float
    reason: str | None
    rank_order: int


class SubmissionRead(TimestampedPublicRead):
    assignment_public_id: str
    import_batch_public_id: str | None
    enrollment_public_id: str | None
    source_entry_name: str
    source_entry_path: str
    matched_by: str | None
    match_confidence: float | None
    match_reason: str | None
    status: str
    canonical_name: str | None
    current_path: str
    assets: list[SubmissionAssetRead] = Field(default_factory=list)
    match_candidates: list[SubmissionMatchCandidateRead] = Field(default_factory=list)


class SubmissionConfirmDecision(BaseModel):
    submission_public_id: str
    enrollment_public_id: str | None = None
    status: str | None = None
    note: str | None = None


class SubmissionImportConfirmRequest(BaseModel):
    items: list[SubmissionConfirmDecision]
