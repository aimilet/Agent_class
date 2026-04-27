use std::fs::File;
use std::path::Path;
use std::time::Duration;

use reqwest::StatusCode;
use reqwest::blocking::{Client, Response, multipart};
use serde::de::DeserializeOwned;

use crate::models::{
    AgentRunRead, ApprovalDecisionRequest, ApprovalTaskRead, AssignmentCreate, AssignmentRead,
    AuditEventRead, CourseCreate, CourseEnrollmentRead, CourseRead, DashboardSnapshot,
    HealthResponse, ManualReviewUpdate, NamingPlanCreate, NamingPlanRead, NamingPolicyCreate,
    NamingPolicyRead, ReviewQuestionItemPatch, ReviewQuestionItemRead, ReviewResultRead,
    ReviewRunCreate, ReviewRunRead, ReviewRuntimeSettingsRead, ReviewRuntimeSettingsUpdate,
    RosterCandidateRead, RosterImportBatchRead, RosterImportConfirmRequest,
    SubmissionImportBatchCreate, SubmissionImportBatchRead, SubmissionImportConfirmRequest,
    SubmissionRead, ToolCallLogRead,
};

#[derive(Clone)]
pub struct ApiClient {
    base_url: String,
    http: Client,
}

impl ApiClient {
    pub fn new(base_url: String) -> Result<Self, String> {
        let http = Client::builder()
            .timeout(Duration::from_secs(900))
            .build()
            .map_err(|err| format!("创建 HTTP 客户端失败：{err}"))?;
        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_owned(),
            http,
        })
    }

    pub fn fetch_snapshot(&self) -> Result<DashboardSnapshot, String> {
        let health = self.get_json("/health").ok();
        let courses = self.get_json("/courses")?;
        Ok(DashboardSnapshot { health, courses })
    }

    pub fn health(&self) -> Result<HealthResponse, String> {
        self.get_json("/health")
    }

    pub fn get_review_settings(&self) -> Result<ReviewRuntimeSettingsRead, String> {
        self.get_json("/system/review-settings")
    }

    pub fn update_review_settings(
        &self,
        payload: &ReviewRuntimeSettingsUpdate,
    ) -> Result<ReviewRuntimeSettingsRead, String> {
        self.put_json("/system/review-settings", payload)
    }

    pub fn create_course(&self, payload: &CourseCreate) -> Result<CourseRead, String> {
        self.post_json("/courses", payload)
    }

    pub fn list_courses(&self) -> Result<Vec<CourseRead>, String> {
        self.get_json("/courses")
    }

    pub fn list_enrollments(
        &self,
        course_public_id: &str,
    ) -> Result<Vec<CourseEnrollmentRead>, String> {
        self.get_json(&format!("/courses/{course_public_id}/enrollments"))
    }

    pub fn create_roster_import(
        &self,
        course_public_id: &str,
        file_paths: &[String],
        parse_mode: &str,
    ) -> Result<RosterImportBatchRead, String> {
        let mut form = multipart::Form::new().text("parse_mode", parse_mode.to_owned());
        for file_path in file_paths {
            let resolved = Path::new(file_path);
            let file = File::open(resolved)
                .map_err(|err| format!("打开名单文件失败：{} ({err})", resolved.display()))?;
            let filename = resolved
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("roster.bin")
                .to_owned();
            form = form.part("files", multipart::Part::reader(file).file_name(filename));
        }
        let response = self
            .http
            .post(self.url(&format!("/courses/{course_public_id}/roster-imports")))
            .multipart(form)
            .send()
            .map_err(|err| format!("创建名单导入批次失败：{err}"))?;
        Self::parse_json(response)
    }

    pub fn run_roster_import(
        &self,
        batch_public_id: &str,
    ) -> Result<RosterImportBatchRead, String> {
        self.post_empty(&format!("/roster-imports/{batch_public_id}/run"))
    }

    pub fn cancel_roster_import(
        &self,
        batch_public_id: &str,
    ) -> Result<RosterImportBatchRead, String> {
        self.post_empty(&format!("/roster-imports/{batch_public_id}/cancel"))
    }

    pub fn get_roster_import(
        &self,
        batch_public_id: &str,
    ) -> Result<RosterImportBatchRead, String> {
        self.get_json(&format!("/roster-imports/{batch_public_id}"))
    }

    pub fn list_roster_candidates(
        &self,
        batch_public_id: &str,
    ) -> Result<Vec<RosterCandidateRead>, String> {
        self.get_json(&format!("/roster-imports/{batch_public_id}/candidates"))
    }

    pub fn confirm_roster_import(
        &self,
        batch_public_id: &str,
        payload: &RosterImportConfirmRequest,
    ) -> Result<RosterImportBatchRead, String> {
        self.post_json(
            &format!("/roster-imports/{batch_public_id}/confirm"),
            payload,
        )
    }

    pub fn apply_roster_import(
        &self,
        batch_public_id: &str,
    ) -> Result<RosterImportBatchRead, String> {
        self.post_empty(&format!("/roster-imports/{batch_public_id}/apply"))
    }

    pub fn create_assignment(
        &self,
        course_public_id: &str,
        payload: &AssignmentCreate,
    ) -> Result<AssignmentRead, String> {
        self.post_json(&format!("/courses/{course_public_id}/assignments"), payload)
    }

    pub fn list_assignments(&self, course_public_id: &str) -> Result<Vec<AssignmentRead>, String> {
        self.get_json(&format!("/courses/{course_public_id}/assignments"))
    }

    pub fn create_submission_import(
        &self,
        assignment_public_id: &str,
        payload: &SubmissionImportBatchCreate,
    ) -> Result<SubmissionImportBatchRead, String> {
        self.post_json(
            &format!("/assignments/{assignment_public_id}/submission-imports"),
            payload,
        )
    }

    pub fn run_submission_import(
        &self,
        batch_public_id: &str,
    ) -> Result<SubmissionImportBatchRead, String> {
        self.post_empty(&format!("/submission-imports/{batch_public_id}/run"))
    }

    pub fn cancel_submission_import(
        &self,
        batch_public_id: &str,
    ) -> Result<SubmissionImportBatchRead, String> {
        self.post_empty(&format!("/submission-imports/{batch_public_id}/cancel"))
    }

    pub fn get_submission_import(
        &self,
        batch_public_id: &str,
    ) -> Result<SubmissionImportBatchRead, String> {
        self.get_json(&format!("/submission-imports/{batch_public_id}"))
    }

    pub fn list_batch_submissions(
        &self,
        batch_public_id: &str,
    ) -> Result<Vec<SubmissionRead>, String> {
        self.get_json(&format!(
            "/submission-imports/{batch_public_id}/submissions"
        ))
    }

    pub fn confirm_submission_import(
        &self,
        batch_public_id: &str,
        payload: &SubmissionImportConfirmRequest,
    ) -> Result<SubmissionImportBatchRead, String> {
        self.post_json(
            &format!("/submission-imports/{batch_public_id}/confirm"),
            payload,
        )
    }

    pub fn apply_submission_import(
        &self,
        batch_public_id: &str,
    ) -> Result<SubmissionImportBatchRead, String> {
        self.post_empty(&format!("/submission-imports/{batch_public_id}/apply"))
    }

    pub fn list_assignment_submissions(
        &self,
        assignment_public_id: &str,
    ) -> Result<Vec<SubmissionRead>, String> {
        self.get_json(&format!("/assignments/{assignment_public_id}/submissions"))
    }

    pub fn create_naming_policy(
        &self,
        assignment_public_id: &str,
        payload: &NamingPolicyCreate,
    ) -> Result<NamingPolicyRead, String> {
        self.post_json(
            &format!("/assignments/{assignment_public_id}/naming-policies"),
            payload,
        )
    }

    pub fn list_naming_policies(
        &self,
        assignment_public_id: &str,
    ) -> Result<Vec<NamingPolicyRead>, String> {
        self.get_json(&format!(
            "/assignments/{assignment_public_id}/naming-policies"
        ))
    }

    pub fn create_naming_plan(
        &self,
        assignment_public_id: &str,
        payload: &NamingPlanCreate,
    ) -> Result<NamingPlanRead, String> {
        self.post_json(
            &format!("/assignments/{assignment_public_id}/naming-plans"),
            payload,
        )
    }

    pub fn get_naming_plan(&self, plan_public_id: &str) -> Result<NamingPlanRead, String> {
        self.get_json(&format!("/naming-plans/{plan_public_id}"))
    }

    pub fn submit_naming_plan_approval(
        &self,
        plan_public_id: &str,
    ) -> Result<ApprovalTaskRead, String> {
        self.post_empty(&format!("/naming-plans/{plan_public_id}/submit-approval"))
    }

    pub fn execute_naming_plan(&self, plan_public_id: &str) -> Result<NamingPlanRead, String> {
        self.post_empty(&format!("/naming-plans/{plan_public_id}/execute"))
    }

    pub fn rollback_naming_plan(&self, plan_public_id: &str) -> Result<NamingPlanRead, String> {
        self.post_empty(&format!("/naming-plans/{plan_public_id}/rollback"))
    }

    pub fn create_review_prep(
        &self,
        assignment_public_id: &str,
        file_paths: &[String],
    ) -> Result<crate::models::ReviewPrepRead, String> {
        let mut form = multipart::Form::new();
        for file_path in file_paths {
            let resolved = Path::new(file_path);
            let file = File::open(resolved)
                .map_err(|err| format!("打开评审材料失败：{} ({err})", resolved.display()))?;
            let filename = resolved
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("material.bin")
                .to_owned();
            form = form.part("files", multipart::Part::reader(file).file_name(filename));
        }
        let response = self
            .http
            .post(self.url(&format!("/assignments/{assignment_public_id}/review-preps")))
            .multipart(form)
            .send()
            .map_err(|err| format!("创建评审初始化失败：{err}"))?;
        Self::parse_json(response)
    }

    pub fn run_review_prep(
        &self,
        review_prep_public_id: &str,
    ) -> Result<crate::models::ReviewPrepRead, String> {
        self.post_empty(&format!("/review-preps/{review_prep_public_id}/run"))
    }

    pub fn cancel_review_prep(
        &self,
        review_prep_public_id: &str,
    ) -> Result<crate::models::ReviewPrepRead, String> {
        self.post_empty(&format!("/review-preps/{review_prep_public_id}/cancel"))
    }

    pub fn get_review_prep(
        &self,
        review_prep_public_id: &str,
    ) -> Result<crate::models::ReviewPrepRead, String> {
        self.get_json(&format!("/review-preps/{review_prep_public_id}"))
    }

    pub fn list_review_questions(
        &self,
        review_prep_public_id: &str,
    ) -> Result<Vec<ReviewQuestionItemRead>, String> {
        self.get_json(&format!("/review-preps/{review_prep_public_id}/questions"))
    }

    pub fn patch_review_question(
        &self,
        item_public_id: &str,
        payload: &ReviewQuestionItemPatch,
    ) -> Result<ReviewQuestionItemRead, String> {
        self.patch_json(&format!("/review-question-items/{item_public_id}"), payload)
    }

    pub fn confirm_review_prep(
        &self,
        review_prep_public_id: &str,
    ) -> Result<crate::models::ReviewPrepRead, String> {
        self.post_empty(&format!("/review-preps/{review_prep_public_id}/confirm"))
    }

    pub fn create_review_run(
        &self,
        assignment_public_id: &str,
        payload: &ReviewRunCreate,
    ) -> Result<ReviewRunRead, String> {
        self.post_json(
            &format!("/assignments/{assignment_public_id}/review-runs"),
            payload,
        )
    }

    pub fn start_review_run(&self, review_run_public_id: &str) -> Result<ReviewRunRead, String> {
        self.post_empty(&format!("/review-runs/{review_run_public_id}/start"))
    }

    pub fn cancel_review_run(&self, review_run_public_id: &str) -> Result<ReviewRunRead, String> {
        self.post_empty(&format!("/review-runs/{review_run_public_id}/cancel"))
    }

    pub fn get_review_run(&self, review_run_public_id: &str) -> Result<ReviewRunRead, String> {
        self.get_json(&format!("/review-runs/{review_run_public_id}"))
    }

    pub fn list_review_results(
        &self,
        review_run_public_id: &str,
    ) -> Result<Vec<ReviewResultRead>, String> {
        self.get_json(&format!("/review-runs/{review_run_public_id}/results"))
    }

    pub fn manual_review_result(
        &self,
        review_result_public_id: &str,
        payload: &ManualReviewUpdate,
    ) -> Result<ReviewResultRead, String> {
        self.patch_json(
            &format!("/review-results/{review_result_public_id}/manual-review"),
            payload,
        )
    }

    pub fn retry_review_run(&self, review_run_public_id: &str) -> Result<ReviewRunRead, String> {
        self.post_empty(&format!("/review-runs/{review_run_public_id}/retry-failed"))
    }

    pub fn publish_review_run(
        &self,
        review_run_public_id: &str,
    ) -> Result<ApprovalTaskRead, String> {
        self.post_empty(&format!("/review-runs/{review_run_public_id}/publish"))
    }

    pub fn approve_task(
        &self,
        approval_task_public_id: &str,
        note: Option<String>,
    ) -> Result<ApprovalTaskRead, String> {
        let payload = ApprovalDecisionRequest {
            operator_note: note,
        };
        self.post_json(
            &format!("/approval-tasks/{approval_task_public_id}/approve"),
            &payload,
        )
    }

    pub fn reject_task(
        &self,
        approval_task_public_id: &str,
        note: Option<String>,
    ) -> Result<ApprovalTaskRead, String> {
        let payload = ApprovalDecisionRequest {
            operator_note: note,
        };
        self.post_json(
            &format!("/approval-tasks/{approval_task_public_id}/reject"),
            &payload,
        )
    }

    pub fn execute_approval_task(
        &self,
        approval_task_public_id: &str,
    ) -> Result<ApprovalTaskRead, String> {
        self.post_empty(&format!(
            "/approval-tasks/{approval_task_public_id}/execute"
        ))
    }

    pub fn list_agent_runs(&self) -> Result<Vec<AgentRunRead>, String> {
        self.get_json("/agent-runs")
    }

    pub fn list_tool_calls(
        &self,
        agent_run_public_id: &str,
    ) -> Result<Vec<ToolCallLogRead>, String> {
        self.get_json(&format!("/agent-runs/{agent_run_public_id}/tool-calls"))
    }

    pub fn list_course_audit_events(
        &self,
        course_public_id: &str,
    ) -> Result<Vec<AuditEventRead>, String> {
        self.get_json(&format!("/courses/{course_public_id}/audit-events"))
    }

    fn get_json<T: DeserializeOwned>(&self, path: &str) -> Result<T, String> {
        let response = self
            .http
            .get(self.url(path))
            .send()
            .map_err(|err| format!("请求 {path} 失败：{err}"))?;
        Self::parse_json(response)
    }

    fn post_json<T: DeserializeOwned, P: serde::Serialize>(
        &self,
        path: &str,
        payload: &P,
    ) -> Result<T, String> {
        let response = self
            .http
            .post(self.url(path))
            .json(payload)
            .send()
            .map_err(|err| format!("请求 {path} 失败：{err}"))?;
        Self::parse_json(response)
    }

    fn patch_json<T: DeserializeOwned, P: serde::Serialize>(
        &self,
        path: &str,
        payload: &P,
    ) -> Result<T, String> {
        let response = self
            .http
            .patch(self.url(path))
            .json(payload)
            .send()
            .map_err(|err| format!("请求 {path} 失败：{err}"))?;
        Self::parse_json(response)
    }

    fn post_empty<T: DeserializeOwned>(&self, path: &str) -> Result<T, String> {
        let response = self
            .http
            .post(self.url(path))
            .send()
            .map_err(|err| format!("请求 {path} 失败：{err}"))?;
        Self::parse_json(response)
    }

    fn put_json<T: DeserializeOwned, P: serde::Serialize>(
        &self,
        path: &str,
        payload: &P,
    ) -> Result<T, String> {
        let response = self
            .http
            .put(self.url(path))
            .json(payload)
            .send()
            .map_err(|err| format!("请求 {path} 失败：{err}"))?;
        Self::parse_json(response)
    }

    fn url(&self, path: &str) -> String {
        format!("{}{}", self.base_url, path)
    }

    fn parse_json<T: DeserializeOwned>(response: Response) -> Result<T, String> {
        let status = response.status();
        if status.is_success() {
            return response
                .json::<T>()
                .map_err(|err| format!("解析响应失败：{err}"));
        }

        let body = response
            .text()
            .unwrap_or_else(|_| format!("HTTP {status}，且响应体读取失败"));
        Err(Self::format_error(status, &body))
    }

    fn format_error(status: StatusCode, body: &str) -> String {
        let trimmed = body.trim();
        if trimmed.is_empty() {
            return format!("HTTP {status}");
        }
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(trimmed) {
            if let Some(message) = json
                .pointer("/error/message")
                .and_then(|value| value.as_str())
            {
                return format!("HTTP {status}: {message}");
            }
            if let Some(detail) = json.get("detail") {
                return format!("HTTP {status}: {detail}");
            }
        }
        format!("HTTP {status}: {trimmed}")
    }
}
