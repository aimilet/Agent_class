from __future__ import annotations

from collections.abc import Iterable

from backend.core.errors import DomainError
from backend.domain.enums import (
    AgentRunStatus,
    ApprovalTaskStatus,
    AssignmentStatus,
    CourseStatus,
    NamingOperationStatus,
    NamingPlanStatus,
    NamingPolicyStatus,
    ReviewPrepStatus,
    ReviewQuestionItemStatus,
    ReviewResultStatus,
    ReviewRunStatus,
    RosterImportBatchStatus,
    SubmissionImportBatchStatus,
    SubmissionStatus,
)


STATE_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "course": {
        CourseStatus.DRAFT: {CourseStatus.INITIALIZING, CourseStatus.FAILED},
        CourseStatus.INITIALIZING: {CourseStatus.ACTIVE, CourseStatus.FAILED},
        CourseStatus.ACTIVE: {CourseStatus.ARCHIVED, CourseStatus.FAILED},
        CourseStatus.FAILED: {CourseStatus.INITIALIZING, CourseStatus.ARCHIVED},
        CourseStatus.ARCHIVED: set(),
    },
    "roster_import_batch": {
        RosterImportBatchStatus.UPLOADED: {RosterImportBatchStatus.QUEUED, RosterImportBatchStatus.CANCELLED},
        RosterImportBatchStatus.QUEUED: {RosterImportBatchStatus.PARSING, RosterImportBatchStatus.CANCELLED},
        RosterImportBatchStatus.PARSING: {
            RosterImportBatchStatus.PARSED,
            RosterImportBatchStatus.NEEDS_REVIEW,
            RosterImportBatchStatus.FAILED,
        },
        RosterImportBatchStatus.PARSED: {RosterImportBatchStatus.CONFIRMED, RosterImportBatchStatus.NEEDS_REVIEW},
        RosterImportBatchStatus.NEEDS_REVIEW: {RosterImportBatchStatus.CONFIRMED, RosterImportBatchStatus.CANCELLED},
        RosterImportBatchStatus.CONFIRMED: {RosterImportBatchStatus.APPLIED, RosterImportBatchStatus.FAILED},
        RosterImportBatchStatus.APPLIED: set(),
        RosterImportBatchStatus.FAILED: {RosterImportBatchStatus.QUEUED, RosterImportBatchStatus.CANCELLED},
        RosterImportBatchStatus.CANCELLED: set(),
    },
    "assignment": {
        AssignmentStatus.DRAFT: {AssignmentStatus.ACCEPTING_SUBMISSIONS},
        AssignmentStatus.ACCEPTING_SUBMISSIONS: {
            AssignmentStatus.SUBMISSIONS_IMPORTED,
            AssignmentStatus.NAMING_READY,
            AssignmentStatus.REVIEW_PREP_READY,
        },
        AssignmentStatus.SUBMISSIONS_IMPORTED: {AssignmentStatus.NAMING_READY, AssignmentStatus.REVIEW_PREP_READY},
        AssignmentStatus.NAMING_READY: {AssignmentStatus.REVIEW_PREP_READY},
        AssignmentStatus.REVIEW_PREP_READY: {AssignmentStatus.REVIEWING},
        AssignmentStatus.REVIEWING: {AssignmentStatus.REVIEWED},
        AssignmentStatus.REVIEWED: {AssignmentStatus.PUBLISHED, AssignmentStatus.ARCHIVED},
        AssignmentStatus.PUBLISHED: {AssignmentStatus.ARCHIVED},
        AssignmentStatus.ARCHIVED: set(),
    },
    "submission_import_batch": {
        SubmissionImportBatchStatus.CREATED: {
            SubmissionImportBatchStatus.SCANNING,
            SubmissionImportBatchStatus.FAILED,
            SubmissionImportBatchStatus.CANCELLED,
        },
        SubmissionImportBatchStatus.SCANNING: {
            SubmissionImportBatchStatus.MATCHING,
            SubmissionImportBatchStatus.FAILED,
            SubmissionImportBatchStatus.CANCELLED,
        },
        SubmissionImportBatchStatus.MATCHING: {
            SubmissionImportBatchStatus.NEEDS_REVIEW,
            SubmissionImportBatchStatus.CONFIRMED,
            SubmissionImportBatchStatus.FAILED,
            SubmissionImportBatchStatus.CANCELLED,
        },
        SubmissionImportBatchStatus.NEEDS_REVIEW: {
            SubmissionImportBatchStatus.CONFIRMED,
            SubmissionImportBatchStatus.FAILED,
            SubmissionImportBatchStatus.CANCELLED,
        },
        SubmissionImportBatchStatus.CONFIRMED: {SubmissionImportBatchStatus.APPLIED, SubmissionImportBatchStatus.FAILED},
        SubmissionImportBatchStatus.APPLIED: set(),
        SubmissionImportBatchStatus.FAILED: {SubmissionImportBatchStatus.SCANNING},
        SubmissionImportBatchStatus.CANCELLED: set(),
    },
    "submission": {
        SubmissionStatus.DISCOVERED: {
            SubmissionStatus.MATCHED,
            SubmissionStatus.AMBIGUOUS,
            SubmissionStatus.UNMATCHED,
            SubmissionStatus.IGNORED,
        },
        SubmissionStatus.MATCHED: {SubmissionStatus.CONFIRMED, SubmissionStatus.NAMING_PENDING},
        SubmissionStatus.AMBIGUOUS: {SubmissionStatus.CONFIRMED, SubmissionStatus.IGNORED},
        SubmissionStatus.UNMATCHED: {SubmissionStatus.CONFIRMED, SubmissionStatus.IGNORED},
        SubmissionStatus.CONFIRMED: {SubmissionStatus.NAMING_PENDING, SubmissionStatus.REVIEW_READY},
        SubmissionStatus.NAMING_PENDING: {SubmissionStatus.NAMED, SubmissionStatus.REVIEW_READY},
        SubmissionStatus.NAMED: {SubmissionStatus.REVIEW_READY},
        SubmissionStatus.REVIEW_READY: {SubmissionStatus.REVIEWING},
        SubmissionStatus.REVIEWING: {SubmissionStatus.REVIEWED, SubmissionStatus.FAILED},
        SubmissionStatus.REVIEWED: {SubmissionStatus.PUBLISHED},
        SubmissionStatus.PUBLISHED: set(),
        SubmissionStatus.FAILED: {SubmissionStatus.REVIEWING},
        SubmissionStatus.IGNORED: set(),
    },
    "naming_policy": {
        NamingPolicyStatus.DRAFT: {NamingPolicyStatus.ACTIVE, NamingPolicyStatus.ARCHIVED},
        NamingPolicyStatus.ACTIVE: {NamingPolicyStatus.SUPERSEDED, NamingPolicyStatus.ARCHIVED},
        NamingPolicyStatus.SUPERSEDED: {NamingPolicyStatus.ARCHIVED},
        NamingPolicyStatus.ARCHIVED: set(),
    },
    "naming_plan": {
        NamingPlanStatus.GENERATED: {NamingPlanStatus.PENDING_APPROVAL, NamingPlanStatus.REJECTED},
        NamingPlanStatus.PENDING_APPROVAL: {NamingPlanStatus.APPROVED, NamingPlanStatus.REJECTED},
        NamingPlanStatus.APPROVED: {NamingPlanStatus.EXECUTING},
        NamingPlanStatus.EXECUTING: {
            NamingPlanStatus.APPLIED,
            NamingPlanStatus.PARTIALLY_APPLIED,
            NamingPlanStatus.FAILED,
        },
        NamingPlanStatus.APPLIED: {NamingPlanStatus.ROLLED_BACK},
        NamingPlanStatus.PARTIALLY_APPLIED: {NamingPlanStatus.ROLLED_BACK},
        NamingPlanStatus.REJECTED: set(),
        NamingPlanStatus.FAILED: set(),
        NamingPlanStatus.ROLLED_BACK: set(),
    },
    "naming_operation": {
        NamingOperationStatus.PLANNED: {NamingOperationStatus.APPROVED, NamingOperationStatus.SKIPPED},
        NamingOperationStatus.APPROVED: {
            NamingOperationStatus.RENAMED,
            NamingOperationStatus.CONFLICTED,
            NamingOperationStatus.FAILED,
        },
        NamingOperationStatus.RENAMED: {NamingOperationStatus.ROLLED_BACK},
        NamingOperationStatus.SKIPPED: set(),
        NamingOperationStatus.CONFLICTED: set(),
        NamingOperationStatus.FAILED: set(),
        NamingOperationStatus.ROLLED_BACK: set(),
    },
    "review_prep": {
        ReviewPrepStatus.DRAFT: {
            ReviewPrepStatus.MATERIAL_PARSING,
            ReviewPrepStatus.FAILED,
            ReviewPrepStatus.CANCELLED,
        },
        ReviewPrepStatus.MATERIAL_PARSING: {
            ReviewPrepStatus.QUESTION_STRUCTURING,
            ReviewPrepStatus.FAILED,
            ReviewPrepStatus.CANCELLED,
        },
        ReviewPrepStatus.QUESTION_STRUCTURING: {ReviewPrepStatus.ANSWER_GENERATING, ReviewPrepStatus.NEEDS_REVIEW},
        ReviewPrepStatus.ANSWER_GENERATING: {
            ReviewPrepStatus.ANSWER_CRITIQUING,
            ReviewPrepStatus.NEEDS_REVIEW,
            ReviewPrepStatus.FAILED,
            ReviewPrepStatus.CANCELLED,
        },
        ReviewPrepStatus.ANSWER_CRITIQUING: {
            ReviewPrepStatus.RUBRIC_GENERATING,
            ReviewPrepStatus.ANSWER_GENERATING,
            ReviewPrepStatus.NEEDS_REVIEW,
            ReviewPrepStatus.CANCELLED,
        },
        ReviewPrepStatus.RUBRIC_GENERATING: {
            ReviewPrepStatus.CONFIRMED,
            ReviewPrepStatus.NEEDS_REVIEW,
            ReviewPrepStatus.CANCELLED,
        },
        ReviewPrepStatus.NEEDS_REVIEW: {
            ReviewPrepStatus.CONFIRMED,
            ReviewPrepStatus.FAILED,
            ReviewPrepStatus.CANCELLED,
        },
        ReviewPrepStatus.CONFIRMED: {ReviewPrepStatus.READY},
        ReviewPrepStatus.READY: set(),
        ReviewPrepStatus.FAILED: set(),
        ReviewPrepStatus.CANCELLED: set(),
    },
    "review_question_item": {
        ReviewQuestionItemStatus.DRAFT: {ReviewQuestionItemStatus.GENERATED, ReviewQuestionItemStatus.DISABLED},
        ReviewQuestionItemStatus.GENERATED: {ReviewQuestionItemStatus.REVISED, ReviewQuestionItemStatus.CONFIRMED},
        ReviewQuestionItemStatus.REVISED: {ReviewQuestionItemStatus.CONFIRMED, ReviewQuestionItemStatus.DISABLED},
        ReviewQuestionItemStatus.CONFIRMED: {ReviewQuestionItemStatus.DISABLED},
        ReviewQuestionItemStatus.DISABLED: set(),
    },
    "review_run": {
        ReviewRunStatus.QUEUED: {ReviewRunStatus.SELECTING_ASSETS, ReviewRunStatus.CANCELLED},
        ReviewRunStatus.SELECTING_ASSETS: {
            ReviewRunStatus.GRADING,
            ReviewRunStatus.FAILED,
            ReviewRunStatus.CANCELLED,
        },
        ReviewRunStatus.GRADING: {
            ReviewRunStatus.VALIDATING,
            ReviewRunStatus.PARTIAL_FAILED,
            ReviewRunStatus.CANCELLED,
        },
        ReviewRunStatus.VALIDATING: {
            ReviewRunStatus.NEEDS_REVIEW,
            ReviewRunStatus.COMPLETED,
            ReviewRunStatus.PARTIAL_FAILED,
            ReviewRunStatus.CANCELLED,
        },
        ReviewRunStatus.NEEDS_REVIEW: {ReviewRunStatus.COMPLETED, ReviewRunStatus.CANCELLED},
        ReviewRunStatus.COMPLETED: set(),
        ReviewRunStatus.PARTIAL_FAILED: {ReviewRunStatus.GRADING, ReviewRunStatus.CANCELLED},
        ReviewRunStatus.FAILED: set(),
        ReviewRunStatus.CANCELLED: set(),
    },
    "review_result": {
        ReviewResultStatus.DRAFT: {ReviewResultStatus.VALIDATED, ReviewResultStatus.NEEDS_MANUAL_REVIEW},
        ReviewResultStatus.VALIDATED: {ReviewResultStatus.FINALIZED},
        ReviewResultStatus.NEEDS_MANUAL_REVIEW: {ReviewResultStatus.FINALIZED},
        ReviewResultStatus.FINALIZED: {ReviewResultStatus.PUBLISHED, ReviewResultStatus.RETRACTED},
        ReviewResultStatus.PUBLISHED: {ReviewResultStatus.RETRACTED},
        ReviewResultStatus.RETRACTED: set(),
    },
    "approval_task": {
        ApprovalTaskStatus.PENDING: {
            ApprovalTaskStatus.APPROVED,
            ApprovalTaskStatus.REJECTED,
            ApprovalTaskStatus.EXPIRED,
            ApprovalTaskStatus.CANCELLED,
        },
        ApprovalTaskStatus.APPROVED: {ApprovalTaskStatus.EXECUTING, ApprovalTaskStatus.CANCELLED},
        ApprovalTaskStatus.REJECTED: set(),
        ApprovalTaskStatus.EXPIRED: set(),
        ApprovalTaskStatus.EXECUTING: {
            ApprovalTaskStatus.EXECUTED,
            ApprovalTaskStatus.PARTIALLY_EXECUTED,
            ApprovalTaskStatus.FAILED,
        },
        ApprovalTaskStatus.EXECUTED: set(),
        ApprovalTaskStatus.PARTIALLY_EXECUTED: set(),
        ApprovalTaskStatus.FAILED: set(),
        ApprovalTaskStatus.CANCELLED: set(),
    },
    "agent_run": {
        AgentRunStatus.QUEUED: {AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED},
        AgentRunStatus.RUNNING: {
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.TIMED_OUT,
            AgentRunStatus.CANCELLED,
        },
        AgentRunStatus.SUCCEEDED: set(),
        AgentRunStatus.FAILED: set(),
        AgentRunStatus.CANCELLED: set(),
        AgentRunStatus.TIMED_OUT: set(),
    },
}


def ensure_transition(machine: str, current: str | None, target: str) -> None:
    if current is None:
        return
    allowed = STATE_TRANSITIONS.get(machine, {}).get(current, set())
    if target not in allowed and target != current:
        raise DomainError(
            f"非法状态迁移：{machine} {current} -> {target}",
            code="invalid_status_transition",
            status_code=409,
            detail={"machine": machine, "current": current, "target": target, "allowed": sorted(allowed)},
        )


def is_terminal_status(machine: str, status: str) -> bool:
    allowed = STATE_TRANSITIONS.get(machine, {}).get(status, set())
    return not bool(allowed)


def valid_targets(machine: str, status: str) -> Iterable[str]:
    return STATE_TRANSITIONS.get(machine, {}).get(status, set())
