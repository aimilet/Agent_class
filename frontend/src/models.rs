#![allow(dead_code)]

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HealthResponse {
    pub app_name: String,
    pub database_url: String,
    pub storage_root: String,
    pub llm_enabled: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct StudentRead {
    pub id: i64,
    pub student_no: Option<String>,
    pub name: String,
    pub class_name: Option<String>,
    pub source_filename: Option<String>,
    pub created_at: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct StudentImportResponse {
    pub imported_count: usize,
    pub skipped_count: usize,
    pub imported: Vec<StudentRead>,
    pub skipped: Vec<String>,
    pub parse_mode_used: String,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RenameRuleCreate {
    pub name: String,
    pub template: String,
    pub description: Option<String>,
    pub assignment_label_default: Option<String>,
    pub match_threshold: f32,
    pub enabled: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RenameRuleRead {
    pub id: i64,
    pub name: String,
    pub template: String,
    pub description: Option<String>,
    pub assignment_label_default: Option<String>,
    pub match_threshold: f32,
    pub enabled: bool,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct RenamePreviewRequest {
    pub directory_path: String,
    pub assignment_label: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RenamePreviewItem {
    pub source_path: String,
    pub target_path: Option<String>,
    pub matched_student: Option<String>,
    pub confidence: f32,
    pub status: String,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RenamePreviewResponse {
    pub directory_path: String,
    pub rule: RenameRuleRead,
    pub items: Vec<RenamePreviewItem>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RenameApplyResponse {
    pub directory_path: String,
    pub renamed_count: usize,
    pub items: Vec<RenamePreviewItem>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RenameAgentPreviewRequest {
    pub directory_path: String,
    pub naming_rule: String,
    pub assignment_label: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RenamePatternSummaryRead {
    pub style_key: String,
    pub count: usize,
    pub description: String,
    pub examples: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RenameAgentAnalyzeResponse {
    pub directory_path: String,
    pub detected_patterns: Vec<RenamePatternSummaryRead>,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RenameAgentPreviewResponse {
    pub directory_path: String,
    pub naming_rule: String,
    pub normalized_template: String,
    pub detected_patterns: Vec<RenamePatternSummaryRead>,
    pub items: Vec<RenamePreviewItem>,
    pub script_path: String,
    pub script_content: String,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RenameAgentApplyResponse {
    pub script_path: String,
    pub renamed_count: usize,
    pub items: Vec<RenamePreviewItem>,
    pub applied: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReviewJobCreate {
    pub title: String,
    pub question: Option<String>,
    pub question_paths: Vec<String>,
    pub reference_answer: Option<String>,
    pub reference_answer_paths: Vec<String>,
    pub rubric: Option<String>,
    pub submission_paths: Vec<String>,
    pub document_parse_mode: String,
    pub score_scale: i32,
    pub run_immediately: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SubmissionLogRead {
    pub id: i64,
    pub submission_id: i64,
    pub stage: String,
    pub level: String,
    pub message: String,
    pub payload: Option<serde_json::Value>,
    pub created_at: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SubmissionRead {
    pub id: i64,
    pub student_id: Option<i64>,
    pub original_filename: String,
    pub stored_path: String,
    pub status: String,
    pub parser_name: Option<String>,
    pub parser_notes: Vec<String>,
    pub images_detected: i64,
    pub matched_student_name: Option<String>,
    pub student_match_method: Option<String>,
    pub student_match_confidence: Option<f32>,
    pub score: Option<f32>,
    pub score_scale: i32,
    pub review_status: String,
    pub review_summary: Option<String>,
    pub teacher_comment: Option<String>,
    pub review_payload: Option<serde_json::Value>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ManualReviewUpdate {
    pub score: f32,
    pub review_summary: String,
    pub teacher_comment: Option<String>,
    pub review_status: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ReviewJobRead {
    pub id: i64,
    pub title: String,
    pub question: String,
    pub reference_answer: Option<String>,
    pub rubric: Option<String>,
    pub document_parse_mode: String,
    pub score_scale: i32,
    pub status: String,
    pub created_at: String,
    pub updated_at: String,
    pub submissions: Vec<SubmissionRead>,
}

#[derive(Debug, Clone)]
pub struct DashboardSnapshot {
    pub health: HealthResponse,
    pub students: Vec<StudentRead>,
    pub rules: Vec<RenameRuleRead>,
    pub jobs: Vec<ReviewJobRead>,
}
