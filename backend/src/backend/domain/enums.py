from __future__ import annotations

from enum import StrEnum


class CourseStatus(StrEnum):
    DRAFT = "draft"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    ARCHIVED = "archived"
    FAILED = "failed"


class EnrollmentStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    REMOVED = "removed"


class RosterImportBatchStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PARSING = "parsing"
    PARSED = "parsed"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    APPLIED = "applied"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CandidateDecisionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CORRECTED = "corrected"


class AssignmentStatus(StrEnum):
    DRAFT = "draft"
    ACCEPTING_SUBMISSIONS = "accepting_submissions"
    SUBMISSIONS_IMPORTED = "submissions_imported"
    NAMING_READY = "naming_ready"
    REVIEW_PREP_READY = "review_prep_ready"
    REVIEWING = "reviewing"
    REVIEWED = "reviewed"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SubmissionImportBatchStatus(StrEnum):
    CREATED = "created"
    SCANNING = "scanning"
    MATCHING = "matching"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    APPLIED = "applied"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SubmissionStatus(StrEnum):
    DISCOVERED = "discovered"
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    CONFIRMED = "confirmed"
    NAMING_PENDING = "naming_pending"
    NAMED = "named"
    REVIEW_READY = "review_ready"
    REVIEWING = "reviewing"
    REVIEWED = "reviewed"
    PUBLISHED = "published"
    FAILED = "failed"
    IGNORED = "ignored"


class NamingPolicyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class NamingPlanStatus(StrEnum):
    GENERATED = "generated"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    APPLIED = "applied"
    PARTIALLY_APPLIED = "partially_applied"
    REJECTED = "rejected"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class NamingOperationStatus(StrEnum):
    PLANNED = "planned"
    APPROVED = "approved"
    RENAMED = "renamed"
    SKIPPED = "skipped"
    CONFLICTED = "conflicted"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ReviewPrepStatus(StrEnum):
    DRAFT = "draft"
    MATERIAL_PARSING = "material_parsing"
    QUESTION_STRUCTURING = "question_structuring"
    ANSWER_GENERATING = "answer_generating"
    ANSWER_CRITIQUING = "answer_critiquing"
    RUBRIC_GENERATING = "rubric_generating"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewQuestionItemStatus(StrEnum):
    DRAFT = "draft"
    GENERATED = "generated"
    REVISED = "revised"
    CONFIRMED = "confirmed"
    DISABLED = "disabled"


class AnswerRoundStatus(StrEnum):
    GENERATED = "generated"
    CRITICIZED = "criticized"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ReviewRunStatus(StrEnum):
    QUEUED = "queued"
    SELECTING_ASSETS = "selecting_assets"
    GRADING = "grading"
    VALIDATING = "validating"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewResultStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    FINALIZED = "finalized"
    PUBLISHED = "published"
    RETRACTED = "retracted"


class ApprovalTaskStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTING = "executing"
    EXECUTED = "executed"
    PARTIALLY_EXECUTED = "partially_executed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class ActorType(StrEnum):
    SYSTEM = "system"
    USER = "user"
    AGENT = "agent"


class ApprovalRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
