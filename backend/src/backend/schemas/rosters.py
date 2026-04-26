from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import FileRefRead, TimestampedPublicRead


class RosterImportBatchRead(TimestampedPublicRead):
    course_public_id: str
    source_files: list[FileRefRead]
    parse_mode: str
    status: str
    summary: dict[str, Any] | None = None
    error_message: str | None = None


class RosterCandidateRead(TimestampedPublicRead):
    batch_public_id: str
    source_file: str
    page_no: int | None
    row_ref: str | None
    student_no: str | None
    name: str
    confidence: float
    raw_fragment: str | None
    decision_status: str
    decision_note: str | None


class RosterCandidateDecision(BaseModel):
    candidate_public_id: str
    decision_status: str = Field(pattern="^(accepted|rejected|corrected)$")
    student_no: str | None = None
    name: str | None = None
    decision_note: str | None = None


class RosterImportConfirmRequest(BaseModel):
    items: list[RosterCandidateDecision]
