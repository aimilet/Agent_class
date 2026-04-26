from __future__ import annotations

from backend.domain.models import (
    AgentRun,
    ApprovalItem,
    ApprovalTask,
    Assignment,
    AuditEvent,
    Course,
    CourseEnrollment,
    NamingOperation,
    NamingPlan,
    NamingPolicy,
    ReviewItemResult,
    ReviewPrep,
    ReviewQuestionItem,
    ReviewResult,
    ReviewRun,
    RosterCandidateRow,
    RosterImportBatch,
    Submission,
    SubmissionAsset,
    SubmissionImportBatch,
    SubmissionMatchCandidate,
    ToolCallLog,
)
from backend.schemas.approvals import ApprovalItemRead, ApprovalTaskRead
from backend.schemas.assignments import AssignmentRead
from backend.schemas.audits import AgentRunRead, AuditEventRead, ToolCallLogRead
from backend.schemas.common import FileRefRead
from backend.schemas.courses import CourseEnrollmentRead, CourseRead
from backend.schemas.naming import NamingOperationRead, NamingPlanRead, NamingPolicyRead
from backend.schemas.review_prep import ReviewPrepRead, ReviewQuestionItemRead
from backend.schemas.review_run import ReviewItemResultRead, ReviewResultRead, ReviewRunRead
from backend.schemas.rosters import RosterCandidateRead, RosterImportBatchRead
from backend.schemas.submissions import (
    SubmissionAssetRead,
    SubmissionImportBatchRead,
    SubmissionMatchCandidateRead,
    SubmissionRead,
)


def file_ref_read(data: dict) -> FileRefRead:
    return FileRefRead(
        original_name=data["original_name"],
        stored_name=data["stored_name"],
        path=data["path"],
        size_bytes=data["size_bytes"],
    )


def course_read(course: Course) -> CourseRead:
    active_roster_batch_id = course.active_roster_batch.public_id if course.active_roster_batch is not None else None
    return CourseRead(
        public_id=course.public_id,
        course_code=course.course_code,
        course_name=course.course_name,
        term=course.term,
        class_label=course.class_label,
        teacher_name=course.teacher_name,
        status=course.status,
        active_roster_batch_id=active_roster_batch_id,
        last_error=course.last_error,
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


def enrollment_read(enrollment: CourseEnrollment) -> CourseEnrollmentRead:
    return CourseEnrollmentRead(
        public_id=enrollment.public_id,
        course_public_id=enrollment.course.public_id,
        person_public_id=enrollment.person.public_id,
        display_student_no=enrollment.display_student_no,
        display_name=enrollment.display_name,
        status=enrollment.status,
        created_at=enrollment.created_at,
        updated_at=enrollment.updated_at,
    )


def roster_batch_read(batch: RosterImportBatch) -> RosterImportBatchRead:
    return RosterImportBatchRead(
        public_id=batch.public_id,
        course_public_id=batch.course.public_id,
        source_files=[file_ref_read(item) for item in batch.source_files_json],
        parse_mode=batch.parse_mode,
        status=batch.status,
        summary=batch.summary_json,
        error_message=batch.error_message,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def roster_candidate_read(candidate: RosterCandidateRow) -> RosterCandidateRead:
    return RosterCandidateRead(
        public_id=candidate.public_id,
        batch_public_id=candidate.batch.public_id,
        source_file=candidate.source_file,
        page_no=candidate.page_no,
        row_ref=candidate.row_ref,
        student_no=candidate.student_no,
        name=candidate.name,
        confidence=candidate.confidence,
        raw_fragment=candidate.raw_fragment,
        decision_status=candidate.decision_status,
        decision_note=candidate.decision_note,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def assignment_read(assignment: Assignment) -> AssignmentRead:
    return AssignmentRead(
        public_id=assignment.public_id,
        course_public_id=assignment.course.public_id,
        seq_no=assignment.seq_no,
        title=assignment.title,
        slug=assignment.slug,
        description=assignment.description,
        due_at=assignment.due_at,
        status=assignment.status,
        review_prep_public_id=assignment.review_prep.public_id if getattr(assignment, "review_prep", None) else None,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def submission_import_batch_read(batch: SubmissionImportBatch) -> SubmissionImportBatchRead:
    return SubmissionImportBatchRead(
        public_id=batch.public_id,
        assignment_public_id=batch.assignment.public_id,
        root_path=batch.root_path,
        status=batch.status,
        summary=batch.summary_json,
        error_message=batch.error_message,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def submission_asset_read(asset: SubmissionAsset) -> SubmissionAssetRead:
    return SubmissionAssetRead(
        public_id=asset.public_id,
        submission_public_id=asset.submission.public_id,
        logical_path=asset.logical_path,
        real_path=asset.real_path,
        file_hash=asset.file_hash,
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        asset_role=asset.asset_role,
        selected_by_agent=asset.selected_by_agent,
        selected_reason=asset.selected_reason,
        is_ignored=asset.is_ignored,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def submission_match_candidate_read(candidate: SubmissionMatchCandidate) -> SubmissionMatchCandidateRead:
    return SubmissionMatchCandidateRead(
        public_id=candidate.public_id,
        submission_public_id=candidate.submission.public_id,
        enrollment_public_id=candidate.submission.enrollment.public_id if candidate.submission.enrollment else "",
        confidence=candidate.confidence,
        reason=candidate.reason,
        rank_order=candidate.rank_order,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def submission_read(submission: Submission) -> SubmissionRead:
    return SubmissionRead(
        public_id=submission.public_id,
        assignment_public_id=submission.assignment.public_id,
        import_batch_public_id=submission.import_batch.public_id if submission.import_batch else None,
        enrollment_public_id=submission.enrollment.public_id if submission.enrollment else None,
        source_entry_name=submission.source_entry_name,
        source_entry_path=submission.source_entry_path,
        matched_by=submission.matched_by,
        match_confidence=submission.match_confidence,
        match_reason=submission.match_reason,
        status=submission.status,
        canonical_name=submission.canonical_name,
        current_path=submission.current_path,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
        assets=[submission_asset_read(asset) for asset in submission.assets],
        match_candidates=[submission_match_candidate_read(item) for item in submission.match_candidates],
    )


def naming_policy_read(policy: NamingPolicy) -> NamingPolicyRead:
    return NamingPolicyRead(
        public_id=policy.public_id,
        assignment_public_id=policy.assignment.public_id,
        template_text=policy.template_text,
        natural_language_rule=policy.natural_language_rule,
        version_no=policy.version_no,
        created_by_agent_run_id=None,
        status=policy.status,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def naming_operation_read(operation: NamingOperation) -> NamingOperationRead:
    return NamingOperationRead(
        public_id=operation.public_id,
        plan_public_id=operation.plan.public_id,
        submission_public_id=operation.submission.public_id,
        source_path=operation.source_path,
        target_path=operation.target_path,
        status=operation.status,
        conflict_strategy=operation.conflict_strategy,
        command_preview=operation.command_preview,
        rollback_info=operation.rollback_info_json,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
    )


def naming_plan_read(plan: NamingPlan) -> NamingPlanRead:
    return NamingPlanRead(
        public_id=plan.public_id,
        assignment_public_id=plan.assignment.public_id,
        policy_public_id=plan.policy.public_id,
        status=plan.status,
        approval_task_public_id=plan.approval_task.public_id if getattr(plan, "approval_task", None) else None,
        summary=plan.summary_json,
        operations=[naming_operation_read(item) for item in plan.operations],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def review_prep_read(prep: ReviewPrep) -> ReviewPrepRead:
    return ReviewPrepRead(
        public_id=prep.public_id,
        assignment_public_id=prep.assignment.public_id,
        status=prep.status,
        source_materials=[file_ref_read(item) for item in prep.source_materials_json],
        version_no=prep.version_no,
        confirmed_at=prep.confirmed_at,
        created_at=prep.created_at,
        updated_at=prep.updated_at,
    )


def review_question_item_read(item: ReviewQuestionItem) -> ReviewQuestionItemRead:
    return ReviewQuestionItemRead(
        public_id=item.public_id,
        review_prep_public_id=item.review_prep.public_id,
        question_no=item.question_no,
        question_full_text=item.question_full_text,
        reference_answer_short=item.reference_answer_short,
        reference_answer_full=item.reference_answer_full,
        rubric_text=item.rubric_text,
        score_weight=item.score_weight,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def review_run_read(review_run: ReviewRun) -> ReviewRunRead:
    return ReviewRunRead(
        public_id=review_run.public_id,
        assignment_public_id=review_run.assignment.public_id,
        review_prep_public_id=review_run.review_prep.public_id,
        status=review_run.status,
        parallelism=review_run.parallelism,
        summary=review_run.summary_json,
        created_at=review_run.created_at,
        updated_at=review_run.updated_at,
    )


def review_item_result_read(item: ReviewItemResult) -> ReviewItemResultRead:
    return ReviewItemResultRead(
        public_id=item.public_id,
        review_result_public_id=item.review_result.public_id,
        question_item_public_id=item.question_item.public_id,
        score=item.score,
        reason=item.reason,
        evidence=item.evidence_json,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def review_result_read(result: ReviewResult) -> ReviewResultRead:
    return ReviewResultRead(
        public_id=result.public_id,
        review_run_public_id=result.review_run.public_id,
        submission_public_id=result.submission.public_id,
        total_score=result.total_score,
        score_scale=result.score_scale,
        summary=result.summary,
        decision=result.decision,
        confidence=result.confidence,
        status=result.status,
        result=result.result_json,
        created_at=result.created_at,
        updated_at=result.updated_at,
        items=[review_item_result_read(item) for item in result.item_results],
    )


def approval_item_read(item: ApprovalItem) -> ApprovalItemRead:
    return ApprovalItemRead(
        public_id=item.public_id,
        approval_task_public_id=item.approval_task.public_id,
        item_type=item.item_type,
        before=item.before_json,
        after=item.after_json,
        risk_level=item.risk_level,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def approval_task_read(task: ApprovalTask) -> ApprovalTaskRead:
    return ApprovalTaskRead(
        public_id=task.public_id,
        object_type=task.object_type,
        object_public_id=task.object_public_id,
        action_type=task.action_type,
        status=task.status,
        title=task.title,
        summary=task.summary,
        command_preview=task.command_preview_json,
        operator_note=task.operator_note,
        items=[approval_item_read(item) for item in task.items],
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def agent_run_read(run: AgentRun) -> AgentRunRead:
    return AgentRunRead.model_validate(run)


def tool_call_log_read(log: ToolCallLog) -> ToolCallLogRead:
    return ToolCallLogRead.model_validate(log)


def audit_event_read(event: AuditEvent) -> AuditEventRead:
    return AuditEventRead.model_validate(event)
