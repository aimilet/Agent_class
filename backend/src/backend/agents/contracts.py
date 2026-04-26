from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CourseInitStudentItem(BaseModel):
    student_no: str | None = None
    name: str
    source_file: str
    page_no: int | None = None
    row_ref: str | None = None
    raw_fragment: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


class CourseInitStructuredOutput(BaseModel):
    students: list[CourseInitStudentItem] = Field(default_factory=list)
    global_notes: list[str] = Field(default_factory=list)


class SubmissionMatchCandidateItem(BaseModel):
    enrollment_public_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    rank_order: int = Field(ge=1, default=1)


class SubmissionMatchItem(BaseModel):
    source_entry_name: str
    source_entry_path: str
    matched_by: str | None = None
    match_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    match_reason: str | None = None
    status: Literal["matched", "ambiguous", "unmatched"]
    canonical_name: str | None = None
    match_candidates: list[SubmissionMatchCandidateItem] = Field(default_factory=list)


class SubmissionMatchStructuredOutput(BaseModel):
    submissions: list[SubmissionMatchItem] = Field(default_factory=list)


class NamingPolicyStructuredOutput(BaseModel):
    template_text: str
    natural_language_rule: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ReviewQuestionDraft(BaseModel):
    question_no: int = Field(ge=1)
    question_full_text: str
    reference_answer_short: str | None = None
    reference_answer_full: str | None = None
    rubric_text: str | None = None
    score_weight: float = Field(default=1.0, gt=0.0)
    notes: list[str] = Field(default_factory=list)


class ReviewMaterialParseStructuredOutput(BaseModel):
    question_items: list[ReviewQuestionDraft] = Field(default_factory=list)


class AnswerGenerationStructuredOutput(BaseModel):
    reference_answer_short: str
    reference_answer_full: str


class AnswerCritiqueStructuredOutput(BaseModel):
    issues: list[str] = Field(default_factory=list)
    suggestion: str


class AnswerJudgeStructuredOutput(BaseModel):
    decision: Literal["accepted", "revise", "needs_review"]
    accepted: bool
    issues: list[str] = Field(default_factory=list)


class AssetSelectionItem(BaseModel):
    public_id: str | None = None
    logical_path: str
    real_path: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    reason: str


class AssetSelectionStructuredOutput(BaseModel):
    selected_assets: list[AssetSelectionItem] = Field(default_factory=list)
    ignored_assets: list[AssetSelectionItem] = Field(default_factory=list)


class GradingItemResult(BaseModel):
    question_no: int = Field(ge=1)
    score: float = Field(ge=0.0)
    reason: str


class GradingStructuredOutput(BaseModel):
    total_score: float = Field(ge=0.0)
    score_scale: int = Field(ge=1)
    summary: str
    decision: str
    confidence: float = Field(ge=0.0, le=1.0)
    item_results: list[GradingItemResult] = Field(default_factory=list)


class GradingValidationStructuredOutput(BaseModel):
    status: Literal["validated", "needs_manual_review"]
    errors: list[str] = Field(default_factory=list)
