#![allow(dead_code)]

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct ReviewRuntimeSettingsRead {
    pub review_prep_max_answer_rounds: i64,
    pub review_run_enable_validation_agent: bool,
    pub review_run_default_parallelism: i64,
    pub default_review_scale: i64,
    pub submission_unpack_max_depth: i64,
    pub submission_unpack_max_files: i64,
    pub vision_max_assets_per_submission: i64,
    pub llm_timeout_seconds: f64,
    pub llm_max_retries: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReviewRuntimeSettingsUpdate {
    pub review_prep_max_answer_rounds: i64,
    pub review_run_enable_validation_agent: bool,
    pub review_run_default_parallelism: i64,
    pub default_review_scale: i64,
    pub submission_unpack_max_depth: i64,
    pub submission_unpack_max_files: i64,
    pub vision_max_assets_per_submission: i64,
    pub llm_timeout_seconds: f64,
    pub llm_max_retries: i64,
}

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct HealthResponse {
    pub app_name: String,
    pub database_url: String,
    pub runtime_root: String,
    pub llm_enabled: bool,
    pub review_runtime_settings: ReviewRuntimeSettingsRead,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct FileRefRead {
    pub original_name: String,
    pub stored_name: String,
    pub path: String,
    pub size_bytes: i64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CourseCreate {
    pub course_code: String,
    pub course_name: String,
    pub term: String,
    pub class_label: String,
    pub teacher_name: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CourseRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub course_code: String,
    pub course_name: String,
    pub term: String,
    pub class_label: String,
    pub teacher_name: Option<String>,
    pub status: String,
    pub active_roster_batch_id: Option<String>,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CourseEnrollmentRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub course_public_id: String,
    pub person_public_id: String,
    pub display_student_no: Option<String>,
    pub display_name: String,
    pub status: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CourseReviewSummaryAssignmentRead {
    pub assignment_public_id: String,
    pub seq_no: i64,
    pub title: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CourseReviewSummaryCellRead {
    pub assignment_public_id: String,
    pub review_result_public_id: Option<String>,
    pub submission_public_id: Option<String>,
    pub score: Option<f32>,
    pub summary: Option<String>,
    pub status: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CourseReviewSummaryRowRead {
    pub enrollment_public_id: String,
    pub student_no: Option<String>,
    pub student_name: String,
    pub results: Vec<CourseReviewSummaryCellRead>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CourseReviewSummaryRead {
    pub course_public_id: String,
    pub assignments: Vec<CourseReviewSummaryAssignmentRead>,
    pub rows: Vec<CourseReviewSummaryRowRead>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RosterImportBatchRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub course_public_id: String,
    pub source_files: Vec<FileRefRead>,
    pub parse_mode: String,
    pub status: String,
    pub summary: Option<serde_json::Value>,
    pub error_message: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RosterCandidateRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub batch_public_id: String,
    pub source_file: String,
    pub page_no: Option<i64>,
    pub row_ref: Option<String>,
    pub student_no: Option<String>,
    pub name: String,
    pub confidence: f32,
    pub raw_fragment: Option<String>,
    pub decision_status: String,
    pub decision_note: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RosterCandidateDecision {
    pub candidate_public_id: String,
    pub decision_status: String,
    pub student_no: Option<String>,
    pub name: Option<String>,
    pub decision_note: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RosterImportConfirmRequest {
    pub items: Vec<RosterCandidateDecision>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AssignmentCreate {
    pub seq_no: i64,
    pub title: String,
    pub description: Option<String>,
    pub due_at: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AssignmentRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub course_public_id: String,
    pub seq_no: i64,
    pub title: String,
    pub slug: String,
    pub description: Option<String>,
    pub due_at: Option<String>,
    pub status: String,
    pub review_prep_public_id: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SubmissionImportBatchCreate {
    pub root_path: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SubmissionImportBatchRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub assignment_public_id: String,
    pub root_path: String,
    pub status: String,
    pub summary: Option<serde_json::Value>,
    pub error_message: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SubmissionAssetRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub submission_public_id: String,
    pub logical_path: String,
    pub real_path: String,
    pub file_hash: Option<String>,
    pub mime_type: Option<String>,
    pub size_bytes: i64,
    pub asset_role: Option<String>,
    pub selected_by_agent: bool,
    pub selected_reason: Option<String>,
    pub is_ignored: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SubmissionMatchCandidateRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub submission_public_id: String,
    pub enrollment_public_id: String,
    pub confidence: f32,
    pub reason: Option<String>,
    pub rank_order: i64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SubmissionRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub assignment_public_id: String,
    pub import_batch_public_id: Option<String>,
    pub enrollment_public_id: Option<String>,
    pub source_entry_name: String,
    pub source_entry_path: String,
    pub matched_by: Option<String>,
    pub match_confidence: Option<f32>,
    pub match_reason: Option<String>,
    pub status: String,
    pub canonical_name: Option<String>,
    pub current_path: String,
    pub assets: Vec<SubmissionAssetRead>,
    pub match_candidates: Vec<SubmissionMatchCandidateRead>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SubmissionConfirmDecision {
    pub submission_public_id: String,
    pub enrollment_public_id: Option<String>,
    pub status: Option<String>,
    pub note: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SubmissionImportConfirmRequest {
    pub items: Vec<SubmissionConfirmDecision>,
}

#[derive(Debug, Clone, Serialize)]
pub struct NamingPolicyCreate {
    pub template_text: Option<String>,
    pub natural_language_rule: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct NamingPolicyRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub assignment_public_id: String,
    pub template_text: String,
    pub natural_language_rule: Option<String>,
    pub version_no: i64,
    pub created_by_agent_run_id: Option<String>,
    pub status: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct NamingPlanCreate {
    pub policy_public_id: Option<String>,
    pub template_text: Option<String>,
    pub natural_language_rule: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct NamingOperationRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub plan_public_id: String,
    pub submission_public_id: String,
    pub source_path: String,
    pub target_path: String,
    pub status: String,
    pub conflict_strategy: Option<String>,
    pub command_preview: Option<String>,
    pub rollback_info: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct NamingPlanRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub assignment_public_id: String,
    pub policy_public_id: String,
    pub status: String,
    pub approval_task_public_id: Option<String>,
    pub summary: Option<serde_json::Value>,
    pub operations: Vec<NamingOperationRead>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ReviewPrepRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub assignment_public_id: String,
    pub status: String,
    pub source_materials: Vec<FileRefRead>,
    pub version_no: i64,
    pub confirmed_at: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ReviewQuestionItemRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub review_prep_public_id: String,
    pub question_no: i64,
    pub question_full_text: String,
    pub reference_answer_short: Option<String>,
    pub reference_answer_full: Option<String>,
    pub rubric_text: Option<String>,
    pub score_weight: f32,
    pub status: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReviewQuestionItemPatch {
    pub question_full_text: Option<String>,
    pub reference_answer_short: Option<String>,
    pub reference_answer_full: Option<String>,
    pub rubric_text: Option<String>,
    pub score_weight: Option<f32>,
    pub status: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReviewRunCreate {
    pub review_prep_public_id: Option<String>,
    pub parallelism: Option<i64>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ReviewRunRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub assignment_public_id: String,
    pub review_prep_public_id: String,
    pub status: String,
    pub parallelism: i64,
    pub summary: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ReviewItemResultRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub review_result_public_id: String,
    pub question_item_public_id: String,
    pub score: f32,
    pub reason: Option<String>,
    pub evidence: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ReviewResultRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub review_run_public_id: String,
    pub submission_public_id: String,
    pub enrollment_public_id: Option<String>,
    pub student_no: Option<String>,
    pub student_name: Option<String>,
    pub source_entry_name: String,
    pub current_path: String,
    pub total_score: Option<f32>,
    pub score_scale: i64,
    pub summary: Option<String>,
    pub decision: Option<String>,
    pub confidence: Option<f32>,
    pub status: String,
    pub result: Option<serde_json::Value>,
    pub items: Vec<ReviewItemResultRead>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ManualReviewUpdate {
    pub total_score: f32,
    pub summary: String,
    pub decision: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ApprovalDecisionRequest {
    pub operator_note: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ApprovalItemRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub approval_task_public_id: String,
    pub item_type: String,
    pub before: Option<serde_json::Value>,
    pub after: Option<serde_json::Value>,
    pub risk_level: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ApprovalTaskRead {
    pub public_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub object_type: String,
    pub object_public_id: String,
    pub action_type: String,
    pub status: String,
    pub title: String,
    pub summary: Option<String>,
    pub command_preview: Vec<serde_json::Value>,
    pub operator_note: Option<String>,
    pub items: Vec<ApprovalItemRead>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AgentRunRead {
    pub public_id: String,
    pub graph_name: String,
    pub agent_name: String,
    pub stage_name: String,
    pub status: String,
    pub model_name: Option<String>,
    pub prompt_version: Option<String>,
    pub input_ref_json: Option<serde_json::Value>,
    pub output_ref_json: Option<serde_json::Value>,
    pub error_message: Option<String>,
    pub started_at: String,
    pub ended_at: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ToolCallLogRead {
    pub public_id: String,
    pub agent_run_id: i64,
    pub tool_name: String,
    pub command_text: Option<String>,
    pub arguments_json: Option<serde_json::Value>,
    pub stdout_ref: Option<String>,
    pub stderr_ref: Option<String>,
    pub exit_code: Option<i64>,
    pub status: String,
    pub started_at: String,
    pub ended_at: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AuditEventRead {
    pub public_id: String,
    pub event_type: String,
    pub object_type: String,
    pub object_public_id: String,
    pub actor_type: String,
    pub actor_id: Option<String>,
    pub event_payload_json: Option<serde_json::Value>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Default)]
pub struct DashboardSnapshot {
    pub health: Option<HealthResponse>,
    pub courses: Vec<CourseRead>,
}
