use std::fs::File;
use std::path::Path;
use std::time::Duration;

use reqwest::blocking::{multipart, Client, Response};
use reqwest::StatusCode;
use serde::de::DeserializeOwned;

use crate::models::{
    DashboardSnapshot, ManualReviewUpdate, RenameAgentAnalyzeResponse,
    RenameAgentApplyResponse, RenameAgentPreviewRequest, RenameAgentPreviewResponse,
    RenameApplyResponse, RenamePreviewRequest, RenamePreviewResponse, RenameRuleCreate,
    RenameRuleRead, ReviewJobCreate, ReviewJobRead, StudentImportResponse, SubmissionLogRead,
    SubmissionRead,
};

#[derive(Clone)]
pub struct ApiClient {
    base_url: String,
    http: Client,
}

impl ApiClient {
    pub fn new(base_url: String) -> Result<Self, String> {
        let http = Client::builder()
            .timeout(Duration::from_secs(600))
            .build()
            .map_err(|err| format!("创建 HTTP 客户端失败：{err}"))?;
        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_owned(),
            http,
        })
    }

    pub fn fetch_snapshot(&self) -> Result<DashboardSnapshot, String> {
        Ok(DashboardSnapshot {
            health: self.get_json("/health")?,
            students: self.get_json("/students")?,
            rules: self.get_json("/rename-rules")?,
            jobs: self.get_json("/review-jobs")?,
        })
    }

    pub fn import_students(
        &self,
        file_path: &str,
        class_name: Option<&str>,
        parse_mode: &str,
    ) -> Result<StudentImportResponse, String> {
        let resolved = Path::new(file_path);
        let file = File::open(resolved)
            .map_err(|err| format!("打开名单文件失败：{} ({err})", resolved.display()))?;
        let filename = resolved
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("roster.bin")
            .to_owned();

        let part = multipart::Part::reader(file).file_name(filename);
        let mut form = multipart::Form::new()
            .part("file", part)
            .text("parse_mode", parse_mode.to_owned());
        if let Some(value) = class_name.filter(|value| !value.trim().is_empty()) {
            form = form.text("class_name", value.to_owned());
        }

        let response = self
            .http
            .post(self.url("/students/import"))
            .multipart(form)
            .send()
            .map_err(|err| format!("导入名单请求失败：{err}"))?;
        Self::parse_json(response)
    }

    pub fn create_rule(&self, payload: &RenameRuleCreate) -> Result<RenameRuleRead, String> {
        let response = self
            .http
            .post(self.url("/rename-rules"))
            .json(payload)
            .send()
            .map_err(|err| format!("创建规则失败：{err}"))?;
        Self::parse_json(response)
    }

    pub fn preview_rename(
        &self,
        rule_id: i64,
        payload: &RenamePreviewRequest,
    ) -> Result<RenamePreviewResponse, String> {
        let response = self
            .http
            .post(self.url(&format!("/rename-rules/{rule_id}/preview")))
            .json(payload)
            .send()
            .map_err(|err| format!("改名预览失败：{err}"))?;
        Self::parse_json(response)
    }

    pub fn apply_rename(
        &self,
        rule_id: i64,
        payload: &RenamePreviewRequest,
    ) -> Result<RenameApplyResponse, String> {
        let response = self
            .http
            .post(self.url(&format!("/rename-rules/{rule_id}/apply")))
            .json(payload)
            .send()
            .map_err(|err| format!("执行改名失败：{err}"))?;
        Self::parse_json(response)
    }

    pub fn analyze_rename_agent(
        &self,
        directory_path: &str,
    ) -> Result<RenameAgentAnalyzeResponse, String> {
        let response = self
            .http
            .post(self.url("/rename-agent/analyze"))
            .json(&serde_json::json!({ "directory_path": directory_path }))
            .send()
            .map_err(|err| format!("分析命名形式失败：{err}"))?;
        Self::parse_json(response)
    }

    pub fn preview_rename_agent(
        &self,
        payload: &RenameAgentPreviewRequest,
    ) -> Result<RenameAgentPreviewResponse, String> {
        let response = self
            .http
            .post(self.url("/rename-agent/preview"))
            .json(payload)
            .send()
            .map_err(|err| format!("Agent 改名预览失败：{err}"))?;
        Self::parse_json(response)
    }

    pub fn apply_rename_agent(
        &self,
        script_path: &str,
    ) -> Result<RenameAgentApplyResponse, String> {
        let response = self
            .http
            .post(self.url("/rename-agent/apply"))
            .json(&serde_json::json!({ "script_path": script_path }))
            .send()
            .map_err(|err| format!("执行 Agent 改名失败：{err}"))?;
        Self::parse_json(response)
    }

    pub fn create_review_job(&self, payload: &ReviewJobCreate) -> Result<ReviewJobRead, String> {
        let response = self
            .http
            .post(self.url("/review-jobs"))
            .json(payload)
            .send()
            .map_err(|err| format!("创建审阅任务失败：{err}"))?;
        Self::parse_json(response)
    }

    pub fn get_submission_logs(&self, submission_id: i64) -> Result<Vec<SubmissionLogRead>, String> {
        self.get_json(&format!("/submissions/{submission_id}/logs"))
    }

    pub fn patch_submission_manual_review(
        &self,
        submission_id: i64,
        payload: &ManualReviewUpdate,
    ) -> Result<SubmissionRead, String> {
        let response = self
            .http
            .patch(self.url(&format!("/submissions/{submission_id}/manual-review")))
            .json(payload)
            .send()
            .map_err(|err| format!("保存人工复核失败：{err}"))?;
        Self::parse_json(response)
    }

    fn get_json<T: DeserializeOwned>(&self, path: &str) -> Result<T, String> {
        let response = self
            .http
            .get(self.url(path))
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
            if let Some(detail) = json.get("detail") {
                return format!("HTTP {status}: {detail}");
            }
        }
        format!("HTTP {status}: {trimmed}")
    }
}
