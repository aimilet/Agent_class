use std::collections::VecDeque;
use std::fs;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::thread;

use eframe::CreationContext;
use eframe::egui::{
    self, Color32, CornerRadius, FontDefinitions, FontFamily, FontId, Margin, RichText, Stroke,
    TextEdit, Ui,
};
use rfd::FileDialog;

use crate::api::ApiClient;
use crate::models::{
    DashboardSnapshot, HealthResponse, ManualReviewUpdate, RenameAgentAnalyzeResponse,
    RenameAgentApplyResponse, RenameAgentPreviewRequest, RenameAgentPreviewResponse,
    RenameApplyResponse, RenamePreviewItem, RenamePreviewRequest, RenamePreviewResponse,
    RenameRuleCreate, RenameRuleRead, ReviewJobCreate, ReviewJobRead, StudentImportResponse,
    StudentRead, SubmissionLogRead, SubmissionRead,
};

const MAX_BACKEND_LOG_LINES: usize = 500;
const CJK_FONT_NAME: &str = "noto_sans_cjk_sc";

const ROSTER_PARSE_MODES: [(&str, &str); 3] = [
    ("auto", "自动"),
    ("local_only", "仅本地规则"),
    ("agent_layout", "Agent 布局识别"),
];

const REVIEW_PARSE_MODES: [(&str, &str); 3] = [
    ("auto", "自动"),
    ("local_ocr", "本地 OCR / 文本"),
    ("agent_vision", "视觉评分 Agent"),
];

const EXECUTION_STATUS_FILTERS: [(&str, &str); 4] = [
    ("all", "全部执行状态"),
    ("pending", "待处理"),
    ("completed", "已完成"),
    ("failed", "失败"),
];

const REVIEW_STATUS_FILTERS: [(&str, &str); 4] = [
    ("all", "全部复核状态"),
    ("auto_reviewed", "自动评审"),
    ("reviewed", "已人工复核"),
    ("needs_followup", "需跟进"),
];

const MANUAL_REVIEW_STATUS_OPTIONS: [(&str, &str); 2] = [
    ("reviewed", "已人工复核"),
    ("needs_followup", "需跟进"),
];

#[derive(Clone, Copy, PartialEq, Eq)]
enum WorkspacePage {
    Overview,
    Setup,
    Rename,
    Review,
    ReviewDesk,
}

impl WorkspacePage {
    const ALL: [Self; 5] = [
        Self::Overview,
        Self::Setup,
        Self::Rename,
        Self::Review,
        Self::ReviewDesk,
    ];

    fn title(self) -> &'static str {
        match self {
            Self::Overview => "总览",
            Self::Setup => "数据准备",
            Self::Rename => "批量改名",
            Self::Review => "自动审阅",
            Self::ReviewDesk => "人工复核",
        }
    }

    fn summary(self) -> &'static str {
        match self {
            Self::Overview => "先看当前系统状态、关键指标和最近产出。",
            Self::Setup => "集中处理后端托管、名单导入和规则维护。",
            Self::Rename => "把规则改名与 Agent 改名拆成独立工作区。",
            Self::Review => "创建自动审阅任务，并管理任务导出。",
            Self::ReviewDesk => "专注筛选、人工复核和单份日志查看。",
        }
    }
}

pub struct AssistantApp {
    backend_url: String,
    health: Option<HealthResponse>,
    students: Vec<StudentRead>,
    rules: Vec<RenameRuleRead>,
    jobs: Vec<ReviewJobRead>,
    selected_rule_id: Option<i64>,
    selected_job_id: Option<i64>,
    selected_submission_id: Option<i64>,
    submission_logs: Vec<SubmissionLogRead>,
    rename_preview: Option<RenamePreviewResponse>,
    rename_apply: Option<RenameApplyResponse>,
    rename_agent_analysis: Option<RenameAgentAnalyzeResponse>,
    rename_agent_preview: Option<RenameAgentPreviewResponse>,
    rename_agent_apply: Option<RenameAgentApplyResponse>,
    last_import: Option<StudentImportResponse>,
    status: String,
    pending_tasks: usize,
    event_tx: Sender<WorkerEvent>,
    event_rx: Receiver<WorkerEvent>,
    backend_control: BackendControl,
    import_form: ImportForm,
    rule_form: RuleForm,
    rename_form: RenameForm,
    rename_agent_form: RenameAgentForm,
    review_form: ReviewForm,
    filter_form: SubmissionFilterForm,
    manual_review_form: ManualReviewForm,
    active_page: WorkspacePage,
}

struct BackendControl {
    backend_dir: String,
    child: Option<Child>,
    state: String,
    logs: VecDeque<String>,
}

struct ImportForm {
    file_path: String,
    class_name: String,
    parse_mode: String,
}

struct RuleForm {
    name: String,
    template: String,
    description: String,
    assignment_label_default: String,
    match_threshold: String,
}

#[derive(Default)]
struct RenameForm {
    directory_path: String,
    assignment_label: String,
}

#[derive(Default)]
struct RenameAgentForm {
    directory_path: String,
    assignment_label: String,
    naming_rule: String,
}

struct ReviewForm {
    title: String,
    question: String,
    question_paths: Vec<String>,
    reference_answer: String,
    reference_answer_paths: Vec<String>,
    rubric: String,
    document_parse_mode: String,
    submission_paths: Vec<String>,
}

struct SubmissionFilterForm {
    keyword: String,
    execution_status: String,
    review_status: String,
    only_unmatched: bool,
}

struct ManualReviewForm {
    bound_submission_id: Option<i64>,
    score_input: String,
    review_summary: String,
    teacher_comment: String,
    review_status: String,
}

enum WorkerEvent {
    TaskStarted(String),
    TaskFinished(String),
    SnapshotLoaded(DashboardSnapshot),
    ImportCompleted(StudentImportResponse),
    RenamePreviewLoaded(RenamePreviewResponse),
    RenameApplied(RenameApplyResponse),
    RenameAgentAnalyzed(RenameAgentAnalyzeResponse),
    RenameAgentPreviewLoaded(RenameAgentPreviewResponse),
    RenameAgentApplied(RenameAgentApplyResponse),
    ReviewCreated(ReviewJobRead),
    SubmissionLogsLoaded(i64, Vec<SubmissionLogRead>),
    ManualReviewSaved(i64),
    BackendLogLine(String),
    Error(String),
}

impl Default for RuleForm {
    fn default() -> Self {
        Self {
            name: String::new(),
            template: "{assignment}_{student_no}_{name}".to_owned(),
            description: String::new(),
            assignment_label_default: String::new(),
            match_threshold: "76".to_owned(),
        }
    }
}

impl Default for ImportForm {
    fn default() -> Self {
        Self {
            file_path: String::new(),
            class_name: String::new(),
            parse_mode: "auto".to_owned(),
        }
    }
}

impl Default for ReviewForm {
    fn default() -> Self {
        Self {
            title: String::new(),
            question: String::new(),
            question_paths: Vec::new(),
            reference_answer: String::new(),
            reference_answer_paths: Vec::new(),
            rubric: String::new(),
            document_parse_mode: "auto".to_owned(),
            submission_paths: Vec::new(),
        }
    }
}

impl Default for SubmissionFilterForm {
    fn default() -> Self {
        Self {
            keyword: String::new(),
            execution_status: "all".to_owned(),
            review_status: "all".to_owned(),
            only_unmatched: false,
        }
    }
}

impl Default for ManualReviewForm {
    fn default() -> Self {
        Self {
            bound_submission_id: None,
            score_input: "0".to_owned(),
            review_summary: String::new(),
            teacher_comment: String::new(),
            review_status: "reviewed".to_owned(),
        }
    }
}

impl AssistantApp {
    pub fn new(cc: &CreationContext<'_>) -> Self {
        install_cjk_font(&cc.egui_ctx);
        apply_macos_theme(&cc.egui_ctx);
        cc.egui_ctx.set_pixels_per_point(1.05);

        let (event_tx, event_rx) = channel();
        let app = Self {
            backend_url: "http://127.0.0.1:18080".to_owned(),
            health: None,
            students: Vec::new(),
            rules: Vec::new(),
            jobs: Vec::new(),
            selected_rule_id: None,
            selected_job_id: None,
            selected_submission_id: None,
            submission_logs: Vec::new(),
            rename_preview: None,
            rename_apply: None,
            rename_agent_analysis: None,
            rename_agent_preview: None,
            rename_agent_apply: None,
            last_import: None,
            status: "桌面端已启动，等待连接后端".to_owned(),
            pending_tasks: 0,
            event_tx,
            event_rx,
            backend_control: BackendControl {
                backend_dir: detect_backend_dir().display().to_string(),
                child: None,
                state: "未托管后端".to_owned(),
                logs: VecDeque::new(),
            },
            import_form: ImportForm::default(),
            rule_form: RuleForm::default(),
            rename_form: RenameForm::default(),
            rename_agent_form: RenameAgentForm::default(),
            review_form: ReviewForm::default(),
            filter_form: SubmissionFilterForm::default(),
            manual_review_form: ManualReviewForm::default(),
            active_page: WorkspacePage::Overview,
        };
        app.spawn_refresh();
        app
    }

    fn spawn_refresh(&self) {
        self.spawn_task("刷新数据", |api| {
            let snapshot = api.fetch_snapshot()?;
            Ok(vec![WorkerEvent::SnapshotLoaded(snapshot)])
        });
    }

    fn spawn_import(&self) {
        let file_path = self.import_form.file_path.trim().to_owned();
        let class_name = trimmed_option(&self.import_form.class_name);
        let parse_mode = self.import_form.parse_mode.clone();
        self.spawn_task("导入名单", move |api| {
            let response = api.import_students(&file_path, class_name.as_deref(), &parse_mode)?;
            let snapshot = api.fetch_snapshot()?;
            Ok(vec![
                WorkerEvent::ImportCompleted(response),
                WorkerEvent::SnapshotLoaded(snapshot),
            ])
        });
    }

    fn spawn_create_rule(&self) {
        let payload = RenameRuleCreate {
            name: self.rule_form.name.trim().to_owned(),
            template: self.rule_form.template.trim().to_owned(),
            description: trimmed_option(&self.rule_form.description),
            assignment_label_default: trimmed_option(&self.rule_form.assignment_label_default),
            match_threshold: self.rule_form.match_threshold.trim().parse().unwrap_or(76.0),
            enabled: true,
        };
        self.spawn_task("创建规则", move |api| {
            api.create_rule(&payload)?;
            let snapshot = api.fetch_snapshot()?;
            Ok(vec![WorkerEvent::SnapshotLoaded(snapshot)])
        });
    }

    fn spawn_preview_rename(&self) {
        let Some(rule_id) = self.selected_rule_id else {
            self.send_error("请先选择一条改名规则。");
            return;
        };
        let payload = RenamePreviewRequest {
            directory_path: self.rename_form.directory_path.trim().to_owned(),
            assignment_label: trimmed_option(&self.rename_form.assignment_label),
        };
        self.spawn_task("预览改名", move |api| {
            let response = api.preview_rename(rule_id, &payload)?;
            Ok(vec![WorkerEvent::RenamePreviewLoaded(response)])
        });
    }

    fn spawn_apply_rename(&self) {
        let Some(rule_id) = self.selected_rule_id else {
            self.send_error("请先选择一条改名规则。");
            return;
        };
        let payload = RenamePreviewRequest {
            directory_path: self.rename_form.directory_path.trim().to_owned(),
            assignment_label: trimmed_option(&self.rename_form.assignment_label),
        };
        self.spawn_task("执行改名", move |api| {
            let response = api.apply_rename(rule_id, &payload)?;
            let snapshot = api.fetch_snapshot()?;
            Ok(vec![
                WorkerEvent::RenameApplied(response),
                WorkerEvent::SnapshotLoaded(snapshot),
            ])
        });
    }

    fn spawn_analyze_rename_agent(&self) {
        let directory_path = self.rename_agent_form.directory_path.trim().to_owned();
        self.spawn_task("统计命名形式", move |api| {
            let response = api.analyze_rename_agent(&directory_path)?;
            Ok(vec![WorkerEvent::RenameAgentAnalyzed(response)])
        });
    }

    fn spawn_preview_rename_agent(&self) {
        let payload = RenameAgentPreviewRequest {
            directory_path: self.rename_agent_form.directory_path.trim().to_owned(),
            naming_rule: self.rename_agent_form.naming_rule.trim().to_owned(),
            assignment_label: trimmed_option(&self.rename_agent_form.assignment_label),
        };
        self.spawn_task("生成 Agent 改名预览", move |api| {
            let response = api.preview_rename_agent(&payload)?;
            Ok(vec![WorkerEvent::RenameAgentPreviewLoaded(response)])
        });
    }

    fn spawn_apply_rename_agent(&self) {
        let script_path = self
            .rename_agent_preview
            .as_ref()
            .map(|response| response.script_path.clone())
            .or_else(|| {
                self.rename_agent_apply
                    .as_ref()
                    .map(|response| response.script_path.clone())
            });
        let Some(script_path) = script_path else {
            self.send_error("请先生成 Agent 改名预览脚本。");
            return;
        };

        self.spawn_task("执行 Agent 改名", move |api| {
            let response = api.apply_rename_agent(&script_path)?;
            Ok(vec![WorkerEvent::RenameAgentApplied(response)])
        });
    }

    fn spawn_create_review(&self) {
        let payload = ReviewJobCreate {
            title: self.review_form.title.trim().to_owned(),
            question: trimmed_option(&self.review_form.question),
            question_paths: self.review_form.question_paths.clone(),
            reference_answer: trimmed_option(&self.review_form.reference_answer),
            reference_answer_paths: self.review_form.reference_answer_paths.clone(),
            rubric: trimmed_option(&self.review_form.rubric),
            submission_paths: self.review_form.submission_paths.clone(),
            document_parse_mode: self.review_form.document_parse_mode.clone(),
            score_scale: 100,
            run_immediately: true,
        };
        self.spawn_task("创建审阅任务", move |api| {
            let job = api.create_review_job(&payload)?;
            let snapshot = api.fetch_snapshot()?;
            Ok(vec![
                WorkerEvent::ReviewCreated(job),
                WorkerEvent::SnapshotLoaded(snapshot),
            ])
        });
    }

    fn spawn_load_logs(&self, submission_id: i64) {
        self.spawn_task("加载日志", move |api| {
            let logs = api.get_submission_logs(submission_id)?;
            Ok(vec![WorkerEvent::SubmissionLogsLoaded(submission_id, logs)])
        });
    }

    fn spawn_save_manual_review(&self) {
        let Some(submission_id) = self.selected_submission_id else {
            self.send_error("请先选择一份作业再保存复核。");
            return;
        };

        let score = self.manual_review_form.score_input.trim().parse::<f32>().unwrap_or(-1.0);
        if !(0.0..=100.0).contains(&score) {
            self.send_error("人工复核分数必须在 0 到 100 之间。");
            return;
        }
        if self.manual_review_form.review_summary.trim().is_empty() {
            self.send_error("人工复核总结不能为空。");
            return;
        }

        let payload = ManualReviewUpdate {
            score,
            review_summary: self.manual_review_form.review_summary.trim().to_owned(),
            teacher_comment: trimmed_option(&self.manual_review_form.teacher_comment),
            review_status: self.manual_review_form.review_status.clone(),
        };

        self.spawn_task("保存人工复核", move |api| {
            api.patch_submission_manual_review(submission_id, &payload)?;
            let snapshot = api.fetch_snapshot()?;
            let logs = api.get_submission_logs(submission_id)?;
            Ok(vec![
                WorkerEvent::ManualReviewSaved(submission_id),
                WorkerEvent::SnapshotLoaded(snapshot),
                WorkerEvent::SubmissionLogsLoaded(submission_id, logs),
            ])
        });
    }

    fn spawn_task<F>(&self, label: &'static str, task: F)
    where
        F: FnOnce(ApiClient) -> Result<Vec<WorkerEvent>, String> + Send + 'static,
    {
        let base_url = self.backend_url.trim().to_owned();
        let sender = self.event_tx.clone();
        thread::spawn(move || {
            sender.send(WorkerEvent::TaskStarted(label.to_owned())).ok();
            let client = match ApiClient::new(base_url) {
                Ok(client) => client,
                Err(err) => {
                    sender.send(WorkerEvent::Error(err)).ok();
                    sender.send(WorkerEvent::TaskFinished(label.to_owned())).ok();
                    return;
                }
            };

            match task(client) {
                Ok(events) => {
                    for event in events {
                        sender.send(event).ok();
                    }
                }
                Err(err) => {
                    sender.send(WorkerEvent::Error(err)).ok();
                }
            }

            sender.send(WorkerEvent::TaskFinished(label.to_owned())).ok();
        });
    }

    fn start_backend_process(&mut self) {
        if self.backend_control.child.is_some() {
            self.status = "后端已经在运行。".to_owned();
            return;
        }

        let backend_dir = PathBuf::from(self.backend_control.backend_dir.trim());
        if !backend_dir.is_dir() {
            self.status = format!("后端目录不存在：{}", backend_dir.display());
            return;
        }

        let command = format!("cd {} && uv run backend", shell_quote(backend_dir.as_path()));
        let mut child = match Command::new("bash")
            .arg("-lc")
            .arg(command)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .stdin(Stdio::null())
            .spawn()
        {
            Ok(child) => child,
            Err(err) => {
                self.status = format!("启动后端失败：{err}");
                return;
            }
        };

        if let Some(stdout) = child.stdout.take() {
            spawn_backend_reader(stdout, self.event_tx.clone(), "STDOUT");
        }
        if let Some(stderr) = child.stderr.take() {
            spawn_backend_reader(stderr, self.event_tx.clone(), "STDERR");
        }

        self.push_backend_log("已启动本地后端进程。");
        self.backend_control.state = "运行中（桌面端托管）".to_owned();
        self.backend_control.child = Some(child);
        self.status = "已尝试启动后端。".to_owned();
    }

    fn stop_backend_process(&mut self) {
        if let Some(mut child) = self.backend_control.child.take() {
            let _ = child.kill();
            let _ = child.wait();
            self.push_backend_log("已停止本地后端进程。");
            self.backend_control.state = "已停止".to_owned();
            self.status = "后端已停止。".to_owned();
        }
    }

    fn restart_backend_process(&mut self) {
        self.stop_backend_process();
        self.start_backend_process();
    }

    fn poll_backend_process(&mut self) {
        if let Some(child) = self.backend_control.child.as_mut() {
            match child.try_wait() {
                Ok(Some(status)) => {
                    self.push_backend_log(&format!("后端进程已退出：{status}"));
                    self.backend_control.child = None;
                    self.backend_control.state = format!("已退出（{status}）");
                }
                Ok(None) => {}
                Err(err) => {
                    self.push_backend_log(&format!("轮询后端状态失败：{err}"));
                    self.backend_control.child = None;
                    self.backend_control.state = "状态未知".to_owned();
                }
            }
        }
    }

    fn push_backend_log(&mut self, line: &str) {
        self.backend_control.logs.push_back(line.to_owned());
        while self.backend_control.logs.len() > MAX_BACKEND_LOG_LINES {
            self.backend_control.logs.pop_front();
        }
    }

    fn drain_events(&mut self) {
        while let Ok(event) = self.event_rx.try_recv() {
            match event {
                WorkerEvent::TaskStarted(label) => {
                    self.pending_tasks += 1;
                    self.status = format!("{label}中...");
                }
                WorkerEvent::TaskFinished(label) => {
                    self.pending_tasks = self.pending_tasks.saturating_sub(1);
                    self.status = if self.pending_tasks == 0 {
                        format!("{label}完成")
                    } else {
                        format!("仍有 {} 个任务处理中", self.pending_tasks)
                    };
                }
                WorkerEvent::SnapshotLoaded(snapshot) => self.apply_snapshot(snapshot),
                WorkerEvent::ImportCompleted(response) => self.last_import = Some(response),
                WorkerEvent::RenamePreviewLoaded(response) => {
                    self.rename_apply = None;
                    self.rename_preview = Some(response);
                }
                WorkerEvent::RenameApplied(response) => {
                    self.rename_preview = None;
                    self.rename_apply = Some(response);
                }
                WorkerEvent::RenameAgentAnalyzed(response) => {
                    self.rename_agent_preview = None;
                    self.rename_agent_apply = None;
                    self.rename_agent_analysis = Some(response);
                }
                WorkerEvent::RenameAgentPreviewLoaded(response) => {
                    self.rename_agent_apply = None;
                    self.rename_agent_analysis = Some(RenameAgentAnalyzeResponse {
                        directory_path: response.directory_path.clone(),
                        detected_patterns: response.detected_patterns.clone(),
                        notes: response.notes.clone(),
                    });
                    self.rename_agent_preview = Some(response);
                }
                WorkerEvent::RenameAgentApplied(response) => {
                    self.rename_agent_apply = Some(response);
                }
                WorkerEvent::ReviewCreated(job) => {
                    self.selected_job_id = Some(job.id);
                    self.selected_submission_id = None;
                    self.submission_logs.clear();
                    self.status = format!("审阅任务已创建：{}", job.title);
                }
                WorkerEvent::SubmissionLogsLoaded(submission_id, logs) => {
                    self.selected_submission_id = Some(submission_id);
                    self.submission_logs = logs;
                    self.status = format!("已加载提交 #{submission_id} 的日志");
                }
                WorkerEvent::ManualReviewSaved(submission_id) => {
                    self.status = format!("已保存提交 #{submission_id} 的人工复核结果");
                }
                WorkerEvent::BackendLogLine(line) => self.push_backend_log(&line),
                WorkerEvent::Error(err) => {
                    self.status = err;
                }
            }
        }
    }

    fn apply_snapshot(&mut self, snapshot: DashboardSnapshot) {
        self.health = Some(snapshot.health);
        self.students = snapshot.students;
        self.rules = snapshot.rules;
        self.jobs = snapshot.jobs;

        if self.selected_rule_id.is_none() {
            self.selected_rule_id = self.rules.first().map(|rule| rule.id);
        }

        if self.selected_job_id.is_none() {
            self.selected_job_id = self.jobs.first().map(|job| job.id);
        } else if self.selected_job().is_none() {
            self.selected_job_id = self.jobs.first().map(|job| job.id);
            self.selected_submission_id = None;
            self.submission_logs.clear();
        }

        if let Some(submission) = self.selected_submission().cloned() {
            self.sync_manual_review_form(&submission);
        } else {
            self.selected_submission_id = None;
            self.submission_logs.clear();
            self.manual_review_form = ManualReviewForm::default();
        }
    }

    fn selected_job(&self) -> Option<&ReviewJobRead> {
        self.jobs
            .iter()
            .find(|job| Some(job.id) == self.selected_job_id)
            .or_else(|| self.jobs.first())
    }

    fn selected_submission(&self) -> Option<&SubmissionRead> {
        self.selected_job().and_then(|job| {
            job.submissions
                .iter()
                .find(|submission| Some(submission.id) == self.selected_submission_id)
        })
    }

    fn sync_manual_review_form(&mut self, submission: &SubmissionRead) {
        if self.manual_review_form.bound_submission_id == Some(submission.id) {
            return;
        }
        self.manual_review_form.bound_submission_id = Some(submission.id);
        self.manual_review_form.score_input = submission
            .score
            .map(|value| format!("{value:.2}"))
            .unwrap_or_else(|| "0".to_owned());
        self.manual_review_form.review_summary = submission.review_summary.clone().unwrap_or_default();
        self.manual_review_form.teacher_comment = submission.teacher_comment.clone().unwrap_or_default();
        self.manual_review_form.review_status = match submission.review_status.as_str() {
            "needs_followup" => "needs_followup".to_owned(),
            _ => "reviewed".to_owned(),
        };
    }

    fn select_submission(&mut self, submission: SubmissionRead) {
        self.selected_submission_id = Some(submission.id);
        self.sync_manual_review_form(&submission);
        self.spawn_load_logs(submission.id);
    }

    fn filtered_submissions(&self, job: &ReviewJobRead) -> Vec<SubmissionRead> {
        let keyword = self.filter_form.keyword.trim().to_lowercase();
        job.submissions
            .iter()
            .filter(|submission| {
                if self.filter_form.execution_status != "all"
                    && submission.status != self.filter_form.execution_status
                {
                    return false;
                }
                if self.filter_form.review_status != "all"
                    && submission.review_status != self.filter_form.review_status
                {
                    return false;
                }
                if self.filter_form.only_unmatched && submission.student_id.is_some() {
                    return false;
                }
                if keyword.is_empty() {
                    return true;
                }
                let haystack = format!(
                    "{} {} {} {}",
                    submission.original_filename,
                    submission
                        .matched_student_name
                        .as_deref()
                        .unwrap_or_default(),
                    submission
                        .review_summary
                        .as_deref()
                        .unwrap_or_default(),
                    submission
                        .student_match_method
                        .as_deref()
                        .unwrap_or_default()
                )
                .to_lowercase();
                haystack.contains(&keyword)
            })
            .cloned()
            .collect()
    }

    fn export_selected_job_json(&mut self) {
        let Some(job) = self.selected_job() else {
            self.status = "请先选择一个任务再导出。".to_owned();
            return;
        };
        let default_name = sanitize_filename(&format!("{}_report.json", job.title));
        if let Some(path) = FileDialog::new().set_file_name(&default_name).save_file() {
            match serde_json::to_string_pretty(job) {
                Ok(content) => match fs::write(&path, content) {
                    Ok(_) => self.status = format!("已导出 JSON：{}", path.display()),
                    Err(err) => self.status = format!("导出 JSON 失败：{err}"),
                },
                Err(err) => self.status = format!("序列化 JSON 失败：{err}"),
            }
        }
    }

    fn export_selected_job_markdown(&mut self) {
        let Some(job) = self.selected_job() else {
            self.status = "请先选择一个任务再导出。".to_owned();
            return;
        };
        let default_name = sanitize_filename(&format!("{}_report.md", job.title));
        if let Some(path) = FileDialog::new().set_file_name(&default_name).save_file() {
            let content = build_markdown_report(job, self.selected_submission(), &self.submission_logs);
            match fs::write(&path, content) {
                Ok(_) => self.status = format!("已导出 Markdown：{}", path.display()),
                Err(err) => self.status = format!("导出 Markdown 失败：{err}"),
            }
        }
    }

    fn send_error(&self, message: &str) {
        self.event_tx
            .send(WorkerEvent::Error(message.to_owned()))
            .ok();
    }

    fn pick_backend_directory(&mut self) {
        if let Some(path) = FileDialog::new().pick_folder() {
            self.backend_control.backend_dir = path.display().to_string();
        }
    }

    fn pick_import_file(&mut self) {
        if let Some(path) = FileDialog::new()
            .add_filter("名单文件", &["csv", "xlsx", "xls", "pdf"])
            .pick_file()
        {
            self.import_form.file_path = path.display().to_string();
        }
    }

    fn pick_rename_directory(&mut self) {
        if let Some(path) = FileDialog::new().pick_folder() {
            self.rename_form.directory_path = path.display().to_string();
        }
    }

    fn pick_rename_agent_directory(&mut self) {
        if let Some(path) = FileDialog::new().pick_folder() {
            self.rename_agent_form.directory_path = path.display().to_string();
        }
    }

    fn add_review_files(&mut self) {
        if let Some(paths) = FileDialog::new()
            .add_filter(
                "作业文件",
                &[
                    "txt", "md", "pdf", "docx", "ppt", "pptx", "pptm", "potx", "potm", "png",
                    "jpg", "jpeg", "bmp", "webp", "tif", "tiff", "zip", "tar", "tgz", "tbz",
                    "tbz2", "txz",
                ],
            )
            .pick_files()
        {
            for path in paths {
                self.push_review_path(path.display().to_string());
            }
        }
    }

    fn add_review_folder(&mut self) {
        if let Some(path) = FileDialog::new().pick_folder() {
            self.push_review_path(path.display().to_string());
        }
    }

    fn add_question_files(&mut self) {
        if let Some(paths) = FileDialog::new()
            .add_filter(
                "题目文件",
                &[
                    "txt", "md", "pdf", "docx", "ppt", "pptx", "pptm", "potx", "potm", "png",
                    "jpg", "jpeg", "bmp", "webp", "tif", "tiff",
                ],
            )
            .pick_files()
        {
            for path in paths {
                Self::push_unique_path(&mut self.review_form.question_paths, path.display().to_string());
            }
        }
    }

    fn add_question_folder(&mut self) {
        if let Some(path) = FileDialog::new().pick_folder() {
            Self::push_unique_path(
                &mut self.review_form.question_paths,
                path.display().to_string(),
            );
        }
    }

    fn add_reference_answer_files(&mut self) {
        if let Some(paths) = FileDialog::new()
            .add_filter(
                "答案文件",
                &[
                    "txt", "md", "pdf", "docx", "ppt", "pptx", "pptm", "potx", "potm", "png",
                    "jpg", "jpeg", "bmp", "webp", "tif", "tiff",
                ],
            )
            .pick_files()
        {
            for path in paths {
                Self::push_unique_path(
                    &mut self.review_form.reference_answer_paths,
                    path.display().to_string(),
                );
            }
        }
    }

    fn add_reference_answer_folder(&mut self) {
        if let Some(path) = FileDialog::new().pick_folder() {
            Self::push_unique_path(
                &mut self.review_form.reference_answer_paths,
                path.display().to_string(),
            );
        }
    }

    fn push_review_path(&mut self, path: String) {
        Self::push_unique_path(&mut self.review_form.submission_paths, path);
    }

    fn push_unique_path(paths: &mut Vec<String>, path: String) {
        if !paths.contains(&path) {
            paths.push(path);
        }
    }

    fn toolbar(&mut self, ui: &mut Ui) {
        let selected_job_title = self.selected_job().map(|job| job.title.clone());
        let task_text = if self.pending_tasks > 0 {
            format!("处理中 {}", self.pending_tasks)
        } else {
            "当前空闲".to_owned()
        };

        ui.horizontal_wrapped(|ui| {
            ui.vertical(|ui| {
                ui.label(RichText::new("助教 Agent").size(26.0).strong());
                ui.label(RichText::new(self.active_page.summary()).color(subtle_text_color()));
            });
            ui.add_space(18.0);
            status_chip(
                ui,
                "后端",
                &self.backend_control.state,
                if self.backend_control.child.is_some() {
                    success_color()
                } else {
                    muted_chip_color()
                },
            );
            status_chip(
                ui,
                "任务",
                &task_text,
                if self.pending_tasks > 0 {
                    warning_color()
                } else {
                    success_color()
                },
            );
            if let Some(title) = selected_job_title {
                status_chip(ui, "当前任务", &title, accent_color());
            }
            ui.add_space(8.0);
            ui.label(RichText::new("后端地址").small().color(subtle_text_color()));
            ui.add(
                TextEdit::singleline(&mut self.backend_url)
                    .desired_width(240.0)
                    .hint_text("http://127.0.0.1:18080"),
            );
            if ui.button("刷新数据").clicked() {
                self.spawn_refresh();
            }
            ui.label(RichText::new(&self.status).color(text_primary_color()).strong());
        });
    }

    fn navigation_panel(&mut self, ui: &mut Ui) {
        ui.vertical(|ui| {
            ui.label(RichText::new("工作区").small().color(subtle_text_color()));
            ui.add_space(6.0);
            for page in WorkspacePage::ALL {
                if navigation_button(ui, page, self.active_page == page).clicked() {
                    self.active_page = page;
                }
                ui.add_space(4.0);
            }

            ui.add_space(10.0);
            section_card(ui, "当前状态", "保持关键状态始终可见。", |ui| {
                ui.label(format!("后端：{}", self.backend_control.state));
                ui.label(format!(
                    "学生 {} · 规则 {} · 任务 {}",
                    self.students.len(),
                    self.rules.len(),
                    self.jobs.len()
                ));
                if let Some(health) = &self.health {
                    ui.label(format!("存储目录：{}", health.storage_root));
                } else {
                    ui.label("还没有连接到本地 API。");
                }
            });
        });
    }

    fn workspace_panel(&mut self, ui: &mut Ui) {
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .show(ui, |ui| {
                self.render_page_header(ui);
                ui.add_space(12.0);
                match self.active_page {
                    WorkspacePage::Overview => self.render_overview_page(ui),
                    WorkspacePage::Setup => self.render_setup_page(ui),
                    WorkspacePage::Rename => self.render_rename_page(ui),
                    WorkspacePage::Review => self.render_review_page(ui),
                    WorkspacePage::ReviewDesk => self.render_review_desk_page(ui),
                }
            });
    }

    fn render_page_header(&mut self, ui: &mut Ui) {
        let page = self.active_page;
        section_card(ui, page.title(), page.summary(), |ui| {
            ui.horizontal_wrapped(|ui| {
                metric_card(
                    ui,
                    "服务",
                    self.health
                        .as_ref()
                        .map(|health| health.app_name.as_str())
                        .unwrap_or("未连接"),
                    self.health
                        .as_ref()
                        .map(|health| if health.llm_enabled { "LLM 已启用" } else { "LLM 未启用" })
                        .unwrap_or("等待连接"),
                );
                metric_card(ui, "学生", &self.students.len().to_string(), "已导入名单");
                metric_card(ui, "规则", &self.rules.len().to_string(), "命名规则");
                metric_card(ui, "任务", &self.jobs.len().to_string(), "审阅任务");
            });
        });
    }

    fn render_overview_page(&mut self, ui: &mut Ui) {
        self.render_runtime_panel(ui);
        ui.add_space(12.0);
        self.render_recent_jobs_summary(ui);
        ui.add_space(12.0);
        self.render_recent_rename(ui);
        if self.rename_agent_analysis.is_some()
            || self.rename_agent_preview.is_some()
            || self.rename_agent_apply.is_some()
        {
            ui.add_space(12.0);
            self.render_rename_agent_result(ui);
        }
    }

    fn render_setup_page(&mut self, ui: &mut Ui) {
        self.render_backend_manager(ui);
        ui.add_space(12.0);
        self.render_import_panel(ui);
        ui.add_space(12.0);
        self.render_rule_editor(ui);
    }

    fn render_rename_page(&mut self, ui: &mut Ui) {
        self.render_rule_rename_panel(ui);
        ui.add_space(12.0);
        self.render_agent_rename_panel(ui);
        ui.add_space(12.0);
        self.render_recent_rename(ui);
        ui.add_space(12.0);
        self.render_rename_agent_result(ui);
    }

    fn render_review_page(&mut self, ui: &mut Ui) {
        self.render_review_builder(ui);
        ui.add_space(12.0);
        self.render_job_selector(ui);
    }

    fn render_review_desk_page(&mut self, ui: &mut Ui) {
        self.render_selected_job(ui);
        ui.add_space(12.0);
        self.render_manual_review_panel(ui);
        ui.add_space(12.0);
        self.render_selected_logs(ui);
    }

    fn render_backend_manager(&mut self, ui: &mut Ui) {
        section_card(ui, "本地后端", "托管后端进程与工作目录。", |ui| {
            ui.label("后端目录");
            ui.horizontal_wrapped(|ui| {
                ui.add(
                    TextEdit::singleline(&mut self.backend_control.backend_dir)
                        .desired_width(360.0),
                );
                if ui.button("选择目录").clicked() {
                    self.pick_backend_directory();
                }
            });
            ui.horizontal_wrapped(|ui| {
                if ui.button("启动后端").clicked() {
                    self.start_backend_process();
                }
                if ui.button("停止后端").clicked() {
                    self.stop_backend_process();
                }
                if ui.button("重启后端").clicked() {
                    self.restart_backend_process();
                }
            });
            ui.label(format!("当前状态：{}", self.backend_control.state));
        });
    }

    fn render_import_panel(&mut self, ui: &mut Ui) {
        section_card(ui, "名单导入", "导入学生名单并选择解析模式。", |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.label("名单文件");
                if ui.button("选择名单文件").clicked() {
                    self.pick_import_file();
                }
            });
            ui.add(
                TextEdit::singleline(&mut self.import_form.file_path)
                    .hint_text("选择 csv / xlsx / xls / pdf")
                    .desired_width(f32::INFINITY),
            );
            ui.label("班级名（可选）");
            ui.add(
                TextEdit::singleline(&mut self.import_form.class_name).desired_width(f32::INFINITY),
            );
            combo_box(
                ui,
                "roster-parse-mode",
                "解析模式",
                &mut self.import_form.parse_mode,
                &ROSTER_PARSE_MODES,
            );
            let can_submit = !self.import_form.file_path.trim().is_empty();
            if ui
                .add_enabled(can_submit, egui::Button::new("导入名单"))
                .clicked()
            {
                self.spawn_import();
            }
            if let Some(result) = &self.last_import {
                ui.separator();
                ui.label(format!(
                    "成功导入 {} 人，跳过 {} 人，模式：{}",
                    result.imported_count, result.skipped_count, result.parse_mode_used
                ));
                for note in &result.notes {
                    ui.label(format!("说明：{note}"));
                }
            }
        });
    }

    fn render_rule_editor(&mut self, ui: &mut Ui) {
        section_card(ui, "改名规则", "维护批量改名时使用的模板与阈值。", |ui| {
            ui.label("规则名称");
            ui.add(TextEdit::singleline(&mut self.rule_form.name).desired_width(f32::INFINITY));
            ui.label("文件名模板");
            ui.add(TextEdit::singleline(&mut self.rule_form.template).desired_width(f32::INFINITY));
            ui.label("默认作业名");
            ui.add(
                TextEdit::singleline(&mut self.rule_form.assignment_label_default)
                    .desired_width(f32::INFINITY),
            );
            ui.label("说明");
            ui.add(
                TextEdit::multiline(&mut self.rule_form.description)
                    .desired_rows(2)
                    .desired_width(f32::INFINITY),
            );
            ui.label("匹配阈值");
            ui.add(
                TextEdit::singleline(&mut self.rule_form.match_threshold).desired_width(120.0),
            );
            let can_submit =
                !self.rule_form.name.trim().is_empty() && !self.rule_form.template.trim().is_empty();
            if ui
                .add_enabled(can_submit, egui::Button::new("保存规则"))
                .clicked()
            {
                self.spawn_create_rule();
            }
        });
    }

    fn render_rule_rename_panel(&mut self, ui: &mut Ui) {
        section_card(ui, "规则改名", "用现有规则批量预览或执行重命名。", |ui| {
            combo_box_rule(ui, &self.rules, &mut self.selected_rule_id);
            ui.horizontal_wrapped(|ui| {
                ui.label("作业目录");
                if ui.button("选择文件夹").clicked() {
                    self.pick_rename_directory();
                }
            });
            ui.add(
                TextEdit::singleline(&mut self.rename_form.directory_path)
                    .hint_text("选择学生作业目录")
                    .desired_width(f32::INFINITY),
            );
            ui.label("作业标签");
            ui.add(
                TextEdit::singleline(&mut self.rename_form.assignment_label)
                    .desired_width(f32::INFINITY),
            );
            let can_submit =
                self.selected_rule_id.is_some() && !self.rename_form.directory_path.trim().is_empty();
            ui.horizontal_wrapped(|ui| {
                if ui
                    .add_enabled(can_submit, egui::Button::new("预览改名"))
                    .clicked()
                {
                    self.spawn_preview_rename();
                }
                if ui
                    .add_enabled(can_submit, egui::Button::new("执行改名"))
                    .clicked()
                {
                    self.spawn_apply_rename();
                }
            });
        });
    }

    fn render_agent_rename_panel(&mut self, ui: &mut Ui) {
        section_card(ui, "Agent 改名", "先识别命名风格，再生成临时脚本。", |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.label("作业目录");
                if ui.button("选择文件夹").clicked() {
                    self.pick_rename_agent_directory();
                }
            });
            ui.add(
                TextEdit::singleline(&mut self.rename_agent_form.directory_path)
                    .hint_text("选择需要 Agent 处理的作业目录")
                    .desired_width(f32::INFINITY),
            );
            ui.label("规范命名要求");
            ui.add(
                TextEdit::multiline(&mut self.rename_agent_form.naming_rule)
                    .desired_rows(3)
                    .desired_width(f32::INFINITY)
                    .hint_text("例如：命名改为 作业名_学号_姓名"),
            );
            ui.label("作业标签（可选）");
            ui.add(
                TextEdit::singleline(&mut self.rename_agent_form.assignment_label)
                    .desired_width(f32::INFINITY),
            );
            let can_analyze = !self.rename_agent_form.directory_path.trim().is_empty();
            let can_preview = can_analyze && !self.rename_agent_form.naming_rule.trim().is_empty();
            let can_apply_agent = self
                .rename_agent_preview
                .as_ref()
                .map(|response| !response.script_path.trim().is_empty())
                .unwrap_or(false)
                || self
                    .rename_agent_apply
                    .as_ref()
                    .map(|response| !response.script_path.trim().is_empty())
                    .unwrap_or(false);
            ui.horizontal_wrapped(|ui| {
                if ui
                    .add_enabled(can_analyze, egui::Button::new("统计命名形式"))
                    .clicked()
                {
                    self.spawn_analyze_rename_agent();
                }
                if ui
                    .add_enabled(can_preview, egui::Button::new("生成预览脚本"))
                    .clicked()
                {
                    self.spawn_preview_rename_agent();
                }
                if ui
                    .add_enabled(can_apply_agent, egui::Button::new("执行生成脚本"))
                    .clicked()
                {
                    self.spawn_apply_rename_agent();
                }
            });
            if let Some(preview) = &self.rename_agent_preview {
                ui.label(format!("当前脚本：{}", preview.script_path));
            }
        });
    }

    fn render_review_builder(&mut self, ui: &mut Ui) {
        section_card(ui, "创建自动审阅任务", "把题目、参考答案和待审阅作业集中整理。", |ui| {
            ui.label("任务标题");
            ui.add(TextEdit::singleline(&mut self.review_form.title).desired_width(f32::INFINITY));
            ui.label("题目文本（可留空，如果下面已添加题目文件）");
            ui.add(
                TextEdit::multiline(&mut self.review_form.question)
                    .desired_rows(4)
                    .desired_width(f32::INFINITY),
            );
            ui.horizontal_wrapped(|ui| {
                if ui.button("添加题目文件").clicked() {
                    self.add_question_files();
                }
                if ui.button("添加题目文件夹").clicked() {
                    self.add_question_folder();
                }
                if ui.button("清空题目文件").clicked() {
                    self.review_form.question_paths.clear();
                }
            });
            if self.review_form.question_paths.is_empty() {
                ui.label("当前没有题目文件路径。");
            } else {
                let mut remove_index: Option<usize> = None;
                for (index, path) in self.review_form.question_paths.iter().enumerate() {
                    ui.horizontal_wrapped(|ui| {
                        ui.label(format!("题目 {}.", index + 1));
                        ui.label(path);
                        if ui.small_button("移除").clicked() {
                            remove_index = Some(index);
                        }
                    });
                }
                if let Some(index) = remove_index {
                    self.review_form.question_paths.remove(index);
                }
            }

            ui.separator();
            ui.label("参考答案文本（可留空，也可只添加答案文件）");
            ui.add(
                TextEdit::multiline(&mut self.review_form.reference_answer)
                    .desired_rows(4)
                    .desired_width(f32::INFINITY),
            );
            ui.horizontal_wrapped(|ui| {
                if ui.button("添加答案文件").clicked() {
                    self.add_reference_answer_files();
                }
                if ui.button("添加答案文件夹").clicked() {
                    self.add_reference_answer_folder();
                }
                if ui.button("清空答案文件").clicked() {
                    self.review_form.reference_answer_paths.clear();
                }
            });
            if self.review_form.reference_answer_paths.is_empty() {
                ui.label("当前没有答案文件路径。");
            } else {
                let mut remove_index: Option<usize> = None;
                for (index, path) in self.review_form.reference_answer_paths.iter().enumerate() {
                    ui.horizontal_wrapped(|ui| {
                        ui.label(format!("答案 {}.", index + 1));
                        ui.label(path);
                        if ui.small_button("移除").clicked() {
                            remove_index = Some(index);
                        }
                    });
                }
                if let Some(index) = remove_index {
                    self.review_form.reference_answer_paths.remove(index);
                }
            }

            ui.separator();
            ui.label("评分规则（可选）");
            ui.add(
                TextEdit::multiline(&mut self.review_form.rubric)
                    .desired_rows(3)
                    .desired_width(f32::INFINITY),
            );
            combo_box(
                ui,
                "review-parse-mode",
                "图像处理 / 审阅模式",
                &mut self.review_form.document_parse_mode,
                &REVIEW_PARSE_MODES,
            );

            ui.horizontal_wrapped(|ui| {
                if ui.button("添加作业文件").clicked() {
                    self.add_review_files();
                }
                if ui.button("添加作业文件夹").clicked() {
                    self.add_review_folder();
                }
                if ui.button("清空列表").clicked() {
                    self.review_form.submission_paths.clear();
                }
            });

            if self.review_form.submission_paths.is_empty() {
                ui.label("当前还没有待审阅路径。");
            } else {
                let mut remove_index: Option<usize> = None;
                for (index, path) in self.review_form.submission_paths.iter().enumerate() {
                    ui.horizontal_wrapped(|ui| {
                        ui.label(format!("{}.", index + 1));
                        ui.label(path);
                        if ui.small_button("移除").clicked() {
                            remove_index = Some(index);
                        }
                    });
                }
                if let Some(index) = remove_index {
                    self.review_form.submission_paths.remove(index);
                }
            }

            ui.label("评分制式：100 分");
            let has_question_source =
                !self.review_form.question.trim().is_empty() || !self.review_form.question_paths.is_empty();
            let can_submit = !self.review_form.title.trim().is_empty()
                && has_question_source
                && !self.review_form.submission_paths.is_empty();
            if ui
                .add_enabled(can_submit, egui::Button::new("创建并执行审阅"))
                .clicked()
            {
                self.spawn_create_review();
            }
        });
    }

    fn render_recent_jobs_summary(&mut self, ui: &mut Ui) {
        section_card(ui, "最近任务", "先看近期任务进展，再进入详细复核。", |ui| {
            if self.jobs.is_empty() {
                ui.label("还没有审阅任务。");
                return;
            }

            for job in self.jobs.iter().take(3) {
                inner_panel_frame().show(ui, |ui| {
                    ui.horizontal_wrapped(|ui| {
                        ui.label(RichText::new(&job.title).strong());
                        ui.label(
                            RichText::new(format!("状态：{}", job.status))
                                .color(status_color(&job.status)),
                        );
                    });
                    ui.label(format!(
                        "解析模式：{} · 提交数 {} · 评分制 {} 分",
                        review_mode_label(&job.document_parse_mode),
                        job.submissions.len(),
                        job.score_scale
                    ));
                });
                ui.add_space(8.0);
            }
        });
    }

    fn render_runtime_panel(&mut self, ui: &mut Ui) {
        section_card(ui, "服务控制与进程日志", "保留后端连接与运行轨迹。", |ui| {
            ui.label(format!("本地后端状态：{}", self.backend_control.state));
            if let Some(health) = &self.health {
                ui.label(format!("数据库：{}", health.database_url));
                ui.label(format!("存储目录：{}", health.storage_root));
            } else {
                ui.label("当前尚未从 API 获取到健康状态。");
            }
            ui.add_space(6.0);
            ui.label("后端日志（最近 500 行）");
            let mut log_text = self
                .backend_control
                .logs
                .iter()
                .cloned()
                .collect::<Vec<_>>()
                .join("\n");
            ui.add(
                TextEdit::multiline(&mut log_text)
                    .desired_rows(10)
                    .desired_width(f32::INFINITY)
                    .font(egui::TextStyle::Monospace)
                    .interactive(false),
            );
        });
    }

    fn render_recent_rename(&mut self, ui: &mut Ui) {
        section_card(ui, "最近改名结果", "查看规则改名的预览或执行结果。", |ui| {
            if let Some(result) = &self.rename_apply {
                ui.label(format!(
                    "已执行目录：{}，本次重命名 {} 个文件",
                    result.directory_path, result.renamed_count
                ));
                rename_table(ui, &result.items);
            } else if let Some(result) = &self.rename_preview {
                ui.label(format!(
                    "预览目录：{}，规则：{}",
                    result.directory_path, result.rule.name
                ));
                rename_table(ui, &result.items);
            } else {
                ui.label("还没有改名结果。");
            }
        });
    }

    fn render_rename_agent_result(&mut self, ui: &mut Ui) {
        section_card(ui, "Agent 改名结果", "展示命名分析、脚本和执行反馈。", |ui| {
            if let Some(preview) = &self.rename_agent_preview {
                ui.label(RichText::new("Agent 已生成命名统计、归一化模板和临时改名脚本").strong());
                ui.label(format!("目录：{}", preview.directory_path));
                ui.label(format!("规范要求：{}", preview.naming_rule));
                ui.label(format!("归一化模板：{}", preview.normalized_template));
                ui.label(format!("脚本路径：{}", preview.script_path));
                if !preview.notes.is_empty() {
                    for note in &preview.notes {
                        ui.label(format!("说明：{note}"));
                    }
                }
                if !preview.detected_patterns.is_empty() {
                    ui.separator();
                    ui.label(RichText::new("命名形式统计").strong());
                    for pattern in &preview.detected_patterns {
                        inner_panel_frame().show(ui, |ui| {
                            ui.label(format!("风格：{}", pattern.style_key));
                            ui.label(format!("数量：{}", pattern.count));
                            ui.label(&pattern.description);
                            if !pattern.examples.is_empty() {
                                ui.label(format!("示例：{}", pattern.examples.join("；")));
                            }
                        });
                        ui.add_space(6.0);
                    }
                }
                ui.separator();
                ui.label(RichText::new("脚本内容预览").strong());
                let mut script_text = preview.script_content.clone();
                ui.add(
                    TextEdit::multiline(&mut script_text)
                        .desired_rows(10)
                        .desired_width(f32::INFINITY)
                        .font(egui::TextStyle::Monospace)
                        .interactive(false),
                );
                ui.separator();
                ui.label(RichText::new("改名预览").strong());
                rename_table(ui, &preview.items);
            } else if let Some(analysis) = &self.rename_agent_analysis {
                ui.label(RichText::new("已完成命名形式统计，等待进一步生成脚本").strong());
                ui.label(format!("目录：{}", analysis.directory_path));
                for note in &analysis.notes {
                    ui.label(format!("说明：{note}"));
                }
                if !analysis.detected_patterns.is_empty() {
                    ui.separator();
                    for pattern in &analysis.detected_patterns {
                        inner_panel_frame().show(ui, |ui| {
                            ui.label(format!("风格：{}", pattern.style_key));
                            ui.label(format!("数量：{}", pattern.count));
                            ui.label(&pattern.description);
                            if !pattern.examples.is_empty() {
                                ui.label(format!("示例：{}", pattern.examples.join("；")));
                            }
                        });
                        ui.add_space(6.0);
                    }
                }
            } else {
                ui.label("还没有 Agent 改名结果。");
            }

            if let Some(result) = &self.rename_agent_apply {
                ui.separator();
                ui.label(
                    RichText::new(format!("已执行 Agent 脚本，本次改名 {} 个文件", result.renamed_count))
                        .strong(),
                );
                ui.label(format!("脚本路径：{}", result.script_path));
                rename_table(ui, &result.items);
            }
        });
    }

    fn render_job_selector(&mut self, ui: &mut Ui) {
        section_card(ui, "任务列表与导出", "管理审阅任务并导出报告。", |ui| {
            ui.horizontal_wrapped(|ui| {
                if ui.button("导出当前任务 Markdown").clicked() {
                    self.export_selected_job_markdown();
                }
                if ui.button("导出当前任务 JSON").clicked() {
                    self.export_selected_job_json();
                }
            });

            if self.jobs.is_empty() {
                ui.label("还没有审阅任务。");
                return;
            }

            for job in self.jobs.clone() {
                inner_panel_frame().show(ui, |ui| {
                    ui.horizontal_wrapped(|ui| {
                        ui.label(RichText::new(&job.title).strong());
                        ui.label(
                            RichText::new(format!("状态：{}", job.status))
                                .color(status_color(&job.status)),
                        );
                        let selected = Some(job.id) == self.selected_job_id;
                        let label = if selected { "当前任务" } else { "查看详情" };
                        if ui.button(label).clicked() {
                            self.selected_job_id = Some(job.id);
                            self.selected_submission_id = None;
                            self.submission_logs.clear();
                            self.manual_review_form = ManualReviewForm::default();
                            self.active_page = WorkspacePage::ReviewDesk;
                        }
                    });
                    ui.label(format!(
                        "解析模式：{}，评分制：{} 分，提交数：{}",
                        review_mode_label(&job.document_parse_mode),
                        job.score_scale,
                        job.submissions.len()
                    ));
                    ui.label(&job.question);
                });
                ui.add_space(8.0);
            }
        });
    }

    fn render_selected_job(&mut self, ui: &mut Ui) {
        section_card(ui, "任务筛选与复核入口", "先筛选，再进入单份作业的人工复核。", |ui| {
            let Some(job) = self.selected_job().cloned() else {
                ui.label("请选择一个任务。");
                return;
            };

            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new(&job.title).heading());
                ui.label(RichText::new(format!("状态：{}", job.status)).color(status_color(&job.status)));
            });
            ui.label(format!(
                "模式：{} | 评分制：{} 分",
                review_mode_label(&job.document_parse_mode),
                job.score_scale
            ));
            if let Some(rubric) = &job.rubric {
                ui.label(format!("评分规则：{rubric}"));
            }

            ui.separator();
            ui.label("筛选条件");
            ui.horizontal_wrapped(|ui| {
                ui.label("关键词");
                ui.add(TextEdit::singleline(&mut self.filter_form.keyword).desired_width(180.0));
                combo_box(
                    ui,
                    "execution-filter",
                    "执行状态",
                    &mut self.filter_form.execution_status,
                    &EXECUTION_STATUS_FILTERS,
                );
                combo_box(
                    ui,
                    "review-filter",
                    "复核状态",
                    &mut self.filter_form.review_status,
                    &REVIEW_STATUS_FILTERS,
                );
            });
            ui.checkbox(&mut self.filter_form.only_unmatched, "只看未匹配学生");

            let filtered = self.filtered_submissions(&job);
            ui.label(format!("筛选后共有 {} 份提交", filtered.len()));
            if filtered.is_empty() {
                ui.label("当前筛选条件下没有提交。");
                return;
            }

            egui::ScrollArea::horizontal()
                .auto_shrink([false, false])
                .show(ui, |ui| {
                    egui::Grid::new("filtered-submissions-grid")
                        .striped(true)
                        .min_col_width(88.0)
                        .show(ui, |ui| {
                            ui.strong("文件");
                            ui.strong("学生");
                            ui.strong("匹配");
                            ui.strong("分数");
                            ui.strong("执行");
                            ui.strong("复核");
                            ui.strong("操作");
                            ui.end_row();
                            for submission in filtered {
                                ui.label(&submission.original_filename);
                                ui.label(submission.matched_student_name.as_deref().unwrap_or("-"));
                                ui.label(format!(
                                    "{} ({})",
                                    submission.student_match_method.as_deref().unwrap_or("-"),
                                    submission
                                        .student_match_confidence
                                        .map(|value| format!("{value:.0}"))
                                        .unwrap_or_else(|| "-".to_owned())
                                ));
                                ui.label(
                                    submission
                                        .score
                                        .map(|value| format!("{value:.2}/{}", submission.score_scale))
                                        .unwrap_or_else(|| "-".to_owned()),
                                );
                                ui.label(
                                    RichText::new(&submission.status)
                                        .color(status_color(&submission.status)),
                                );
                                ui.label(
                                    RichText::new(&submission.review_status)
                                        .color(review_status_color(&submission.review_status)),
                                );
                                let selected = Some(submission.id) == self.selected_submission_id;
                                if ui.button(if selected { "当前" } else { "打开复核" }).clicked() {
                                    self.select_submission(submission.clone());
                                }
                                ui.end_row();
                            }
                        });
                });
        });
    }

    fn render_manual_review_panel(&mut self, ui: &mut Ui) {
        section_card(ui, "人工复核面板", "对单份作业做最终确认并回写。", |ui| {
            let Some(submission) = self.selected_submission().cloned() else {
                ui.label("从上方任务表中选择一份作业，这里会显示复核表单。");
                return;
            };

            self.sync_manual_review_form(&submission);

            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new(&submission.original_filename).strong());
                ui.label(
                    RichText::new(format!("执行状态：{}", submission.status))
                        .color(status_color(&submission.status)),
                );
                ui.label(
                    RichText::new(format!("复核状态：{}", submission.review_status))
                        .color(review_status_color(&submission.review_status)),
                );
            });
            ui.label(format!(
                "匹配学生：{} | 匹配方式：{} | 原始分数：{}",
                submission.matched_student_name.as_deref().unwrap_or("-"),
                submission.student_match_method.as_deref().unwrap_or("-"),
                submission
                    .score
                    .map(|value| format!("{value:.2}/{}", submission.score_scale))
                    .unwrap_or_else(|| "-".to_owned())
            ));
            if !submission.parser_notes.is_empty() {
                ui.label(format!("解析备注：{}", submission.parser_notes.join("；")));
            }

            ui.separator();
            ui.label("人工复核分数");
            ui.add(TextEdit::singleline(&mut self.manual_review_form.score_input).desired_width(120.0));
            combo_box(
                ui,
                "manual-review-status",
                "人工复核结果",
                &mut self.manual_review_form.review_status,
                &MANUAL_REVIEW_STATUS_OPTIONS,
            );
            ui.label("人工复核总结");
            ui.add(
                TextEdit::multiline(&mut self.manual_review_form.review_summary)
                    .desired_rows(4)
                    .desired_width(f32::INFINITY),
            );
            ui.label("教师评语");
            ui.add(
                TextEdit::multiline(&mut self.manual_review_form.teacher_comment)
                    .desired_rows(3)
                    .desired_width(f32::INFINITY),
            );
            ui.horizontal_wrapped(|ui| {
                if ui.button("保存人工复核").clicked() {
                    self.spawn_save_manual_review();
                }
                if ui.button("重置为当前提交内容").clicked() {
                    self.sync_manual_review_form(&submission);
                }
            });
        });
    }

    fn render_selected_logs(&mut self, ui: &mut Ui) {
        section_card(ui, "单份作业日志", "查看该作业的处理轨迹和载荷。", |ui| {
            let Some(submission) = self.selected_submission().cloned() else {
                ui.label("点击“打开复核”后，这里会展示单份作业的处理过程。");
                return;
            };

            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new(&submission.original_filename).strong());
                ui.label(RichText::new(format!("状态：{}", submission.status)).color(status_color(&submission.status)));
                if let Some(name) = &submission.matched_student_name {
                    ui.label(format!("学生：{name}"));
                }
            });
            ui.label(format!(
                "解析器：{} | 图片数：{} | 分数：{} | 教师评语：{}",
                submission.parser_name.as_deref().unwrap_or("-"),
                submission.images_detected,
                submission
                    .score
                    .map(|value| format!("{value:.2}/{}", submission.score_scale))
                    .unwrap_or_else(|| "-".to_owned()),
                submission.teacher_comment.as_deref().unwrap_or("-"),
            ));
            if let Some(summary) = &submission.review_summary {
                ui.label(format!("总结：{summary}"));
            }

            if self.submission_logs.is_empty() {
                ui.label("当前提交还没有日志，或日志尚未加载。");
                return;
            }

            for log in &self.submission_logs {
                inner_panel_frame().show(ui, |ui| {
                    ui.horizontal_wrapped(|ui| {
                        ui.label(RichText::new(&log.stage).strong());
                        ui.label(RichText::new(&log.level).color(level_color(&log.level)));
                        ui.label(RichText::new(&log.created_at).small().color(subtle_text_color()));
                    });
                    ui.label(&log.message);
                    if let Some(payload) = &log.payload {
                        let mut payload_text = json_string(payload);
                        ui.add(
                            TextEdit::multiline(&mut payload_text)
                                .desired_rows(4)
                                .desired_width(f32::INFINITY)
                                .font(egui::TextStyle::Monospace)
                                .interactive(false),
                        );
                    }
                });
                ui.add_space(8.0);
            }
        });
    }
}

impl eframe::App for AssistantApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.poll_backend_process();
        self.drain_events();

        egui::TopBottomPanel::top("toolbar")
            .frame(
                egui::Frame::new()
                    .inner_margin(Margin::symmetric(18, 14))
                    .fill(toolbar_color())
                    .stroke(Stroke::new(1.0, border_color())),
            )
            .show(ctx, |ui| self.toolbar(ui));

        egui::SidePanel::left("sidebar")
            .resizable(true)
            .default_width(230.0)
            .min_width(180.0)
            .frame(
                egui::Frame::new()
                    .inner_margin(Margin::same(16))
                    .fill(sidebar_color())
                    .stroke(Stroke::new(1.0, border_color())),
            )
            .show(ctx, |ui| self.navigation_panel(ui));

        egui::CentralPanel::default()
            .frame(
                egui::Frame::new()
                    .inner_margin(Margin::same(16))
                    .fill(canvas_color()),
            )
            .show(ctx, |ui| self.workspace_panel(ui));
    }
}

impl Drop for AssistantApp {
    fn drop(&mut self) {
        self.stop_backend_process();
    }
}

fn apply_macos_theme(ctx: &egui::Context) {
    let mut style = (*ctx.style()).clone();
    style.spacing.item_spacing = egui::vec2(12.0, 12.0);
    style.spacing.button_padding = egui::vec2(14.0, 10.0);
    style.spacing.interact_size = egui::vec2(40.0, 36.0);
    style.spacing.text_edit_width = 280.0;
    style.spacing.combo_width = 220.0;
    style.spacing.indent = 18.0;
    style.visuals = egui::Visuals::light();
    style.visuals.override_text_color = Some(text_primary_color());
    style.visuals.panel_fill = canvas_color();
    style.visuals.window_fill = surface_color();
    style.visuals.extreme_bg_color = surface_alt_color();
    style.visuals.faint_bg_color = soft_tint(border_color());
    style.visuals.code_bg_color = surface_alt_color();
    style.visuals.window_corner_radius = CornerRadius::same(22);
    style.visuals.menu_corner_radius = CornerRadius::same(16);
    style.visuals.window_stroke = Stroke::new(1.0, border_color());
    style.visuals.widgets.noninteractive.bg_fill = surface_color();
    style.visuals.widgets.noninteractive.weak_bg_fill = surface_color();
    style.visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0, border_color());
    style.visuals.widgets.noninteractive.fg_stroke = Stroke::new(1.0, text_primary_color());
    style.visuals.widgets.noninteractive.corner_radius = CornerRadius::same(14);
    style.visuals.widgets.inactive.bg_fill = surface_color();
    style.visuals.widgets.inactive.weak_bg_fill = surface_alt_color();
    style.visuals.widgets.inactive.bg_stroke = Stroke::new(1.0, border_color());
    style.visuals.widgets.inactive.fg_stroke = Stroke::new(1.0, text_primary_color());
    style.visuals.widgets.inactive.corner_radius = CornerRadius::same(14);
    style.visuals.widgets.hovered.bg_fill = surface_alt_color();
    style.visuals.widgets.hovered.weak_bg_fill = soft_tint(accent_color());
    style.visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, accent_color());
    style.visuals.widgets.hovered.fg_stroke = Stroke::new(1.0, text_primary_color());
    style.visuals.widgets.hovered.corner_radius = CornerRadius::same(14);
    style.visuals.widgets.active.bg_fill = soft_tint(accent_color());
    style.visuals.widgets.active.weak_bg_fill = soft_tint(accent_color());
    style.visuals.widgets.active.bg_stroke = Stroke::new(1.0, accent_color());
    style.visuals.widgets.active.fg_stroke = Stroke::new(1.0, accent_color());
    style.visuals.widgets.active.corner_radius = CornerRadius::same(14);
    style.visuals.widgets.open = style.visuals.widgets.hovered;
    style.visuals.selection.bg_fill = accent_color();
    style.visuals.selection.stroke = Stroke::new(1.0, Color32::WHITE);
    style.text_styles.insert(
        egui::TextStyle::Heading,
        FontId::new(24.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Body,
        FontId::new(15.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Button,
        FontId::new(14.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Small,
        FontId::new(12.0, FontFamily::Proportional),
    );
    ctx.set_style(style);
}

fn section_card<R>(
    ui: &mut Ui,
    title: &str,
    subtitle: &str,
    add_contents: impl FnOnce(&mut Ui) -> R,
) -> R {
    egui::Frame::new()
        .fill(surface_color())
        .stroke(Stroke::new(1.0, border_color()))
        .corner_radius(CornerRadius::same(20))
        .inner_margin(Margin::same(16))
        .show(ui, |ui| {
            ui.label(RichText::new(title).size(20.0).strong().color(text_primary_color()));
            if !subtitle.is_empty() {
                ui.label(RichText::new(subtitle).color(subtle_text_color()));
                ui.add_space(8.0);
            }
            add_contents(ui)
        })
        .inner
}

fn inner_panel_frame() -> egui::Frame {
    egui::Frame::new()
        .fill(surface_alt_color())
        .stroke(Stroke::new(1.0, border_color()))
        .corner_radius(CornerRadius::same(16))
        .inner_margin(Margin::same(12))
}

fn navigation_button(ui: &mut Ui, page: WorkspacePage, selected: bool) -> egui::Response {
    let fill = if selected {
        soft_tint(accent_color())
    } else {
        surface_color()
    };
    let stroke_color = if selected { accent_color() } else { border_color() };
    let text_color = if selected {
        accent_color()
    } else {
        text_primary_color()
    };
    ui.add_sized(
        [ui.available_width(), 42.0],
        egui::Button::new(RichText::new(page.title()).color(text_color).strong())
            .fill(fill)
            .stroke(Stroke::new(1.0, stroke_color))
            .corner_radius(CornerRadius::same(14)),
    )
}

fn status_chip(ui: &mut Ui, label: &str, value: &str, color: Color32) {
    egui::Frame::new()
        .fill(soft_tint(color))
        .stroke(Stroke::new(1.0, color))
        .corner_radius(CornerRadius::same(18))
        .inner_margin(Margin::symmetric(10, 6))
        .show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new(label).small().color(subtle_text_color()));
                ui.label(RichText::new(value).strong().color(text_primary_color()));
            });
        });
}

fn combo_box(
    ui: &mut Ui,
    id: &str,
    label: &str,
    current: &mut String,
    options: &[(&str, &str)],
) {
    ui.label(label);
    egui::ComboBox::from_id_salt(id)
        .selected_text(mode_label(current, options))
        .show_ui(ui, |ui| {
            for (value, title) in options {
                ui.selectable_value(current, (*value).to_owned(), *title);
            }
        });
}

fn combo_box_rule(ui: &mut Ui, rules: &[RenameRuleRead], selected_rule_id: &mut Option<i64>) {
    ui.label("规则");
    egui::ComboBox::from_id_salt("rule-select")
        .selected_text(
            rules.iter()
                .find(|rule| Some(rule.id) == *selected_rule_id)
                .map(|rule| rule.name.clone())
                .unwrap_or_else(|| "请选择规则".to_owned()),
        )
        .show_ui(ui, |ui| {
            for rule in rules {
                ui.selectable_value(
                    selected_rule_id,
                    Some(rule.id),
                    format!("{} ({})", rule.name, rule.template),
                );
            }
        });
}

fn metric_card(ui: &mut Ui, title: &str, value: &str, help: &str) {
    inner_panel_frame().show(ui, |ui| {
        ui.set_min_width(156.0);
        ui.label(RichText::new(title).small().color(subtle_text_color()));
        ui.label(RichText::new(value).size(24.0).strong().color(text_primary_color()));
        ui.label(RichText::new(help).small().color(subtle_text_color()));
    });
}

fn install_cjk_font(ctx: &egui::Context) {
    let mut fonts = FontDefinitions::default();
    fonts.font_data.insert(
        CJK_FONT_NAME.to_owned(),
        egui::FontData::from_static(include_bytes!("../assets/NotoSansCJKsc-Regular.otf")).into(),
    );
    fonts
        .families
        .entry(FontFamily::Proportional)
        .or_default()
        .insert(0, CJK_FONT_NAME.to_owned());
    fonts
        .families
        .entry(FontFamily::Monospace)
        .or_default()
        .insert(0, CJK_FONT_NAME.to_owned());
    ctx.set_fonts(fonts);
}

fn rename_table(ui: &mut Ui, items: &[RenamePreviewItem]) {
    egui::ScrollArea::horizontal()
        .auto_shrink([false, false])
        .show(ui, |ui| {
            egui::Grid::new("rename-grid")
                .striped(true)
                .min_col_width(90.0)
                .show(ui, |ui| {
                    ui.strong("原文件");
                    ui.strong("目标文件");
                    ui.strong("匹配学生");
                    ui.strong("置信度");
                    ui.strong("状态");
                    ui.strong("说明");
                    ui.end_row();
                    for item in items {
                        ui.label(&item.source_path);
                        ui.label(item.target_path.as_deref().unwrap_or("-"));
                        ui.label(item.matched_student.as_deref().unwrap_or("-"));
                        ui.label(format!("{:.2}", item.confidence));
                        ui.label(RichText::new(&item.status).color(status_color(&item.status)));
                        ui.label(item.reason.as_deref().unwrap_or("-"));
                        ui.end_row();
                    }
                });
        });
}

fn review_mode_label(value: &str) -> String {
    mode_label(value, &REVIEW_PARSE_MODES)
}

fn mode_label(value: &str, options: &[(&str, &str)]) -> String {
    options
        .iter()
        .find(|(key, _)| *key == value)
        .map(|(_, title)| (*title).to_owned())
        .unwrap_or_else(|| value.to_owned())
}

fn status_color(status: &str) -> Color32 {
    match status {
        "completed" | "pass" | "renamed" => success_color(),
        "running" | "pending" | "ready" => warning_color(),
        "failed" | "partial_failed" | "needs_revision" | "error" => danger_color(),
        _ => muted_chip_color(),
    }
}

fn review_status_color(status: &str) -> Color32 {
    match status {
        "reviewed" => accent_color(),
        "needs_followup" => danger_color(),
        "auto_reviewed" => muted_chip_color(),
        _ => muted_chip_color(),
    }
}

fn level_color(level: &str) -> Color32 {
    match level {
        "info" => accent_color(),
        "warning" => warning_color(),
        "error" => danger_color(),
        _ => muted_chip_color(),
    }
}

fn canvas_color() -> Color32 {
    Color32::from_rgb(242, 244, 247)
}

fn toolbar_color() -> Color32 {
    Color32::from_rgb(246, 247, 249)
}

fn sidebar_color() -> Color32 {
    Color32::from_rgb(237, 240, 244)
}

fn surface_color() -> Color32 {
    Color32::from_rgb(252, 252, 253)
}

fn surface_alt_color() -> Color32 {
    Color32::from_rgb(245, 247, 250)
}

fn border_color() -> Color32 {
    Color32::from_rgb(218, 223, 230)
}

fn text_primary_color() -> Color32 {
    Color32::from_rgb(39, 44, 52)
}

fn subtle_text_color() -> Color32 {
    Color32::from_rgb(111, 118, 130)
}

fn accent_color() -> Color32 {
    Color32::from_rgb(79, 111, 201)
}

fn success_color() -> Color32 {
    Color32::from_rgb(49, 132, 92)
}

fn warning_color() -> Color32 {
    Color32::from_rgb(201, 129, 48)
}

fn danger_color() -> Color32 {
    Color32::from_rgb(191, 75, 75)
}

fn muted_chip_color() -> Color32 {
    Color32::from_rgb(134, 142, 154)
}

fn soft_tint(color: Color32) -> Color32 {
    Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), 28)
}

fn trimmed_option(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_owned())
    }
}

fn json_string(value: &serde_json::Value) -> String {
    serde_json::to_string_pretty(value).unwrap_or_else(|_| value.to_string())
}

fn sanitize_filename(name: &str) -> String {
    name.chars()
        .map(|ch| match ch {
            '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => '_',
            _ => ch,
        })
        .collect()
}

fn shell_quote(path: &Path) -> String {
    let text = path.display().to_string().replace('\'', "'\"'\"'");
    format!("'{text}'")
}

fn spawn_backend_reader<R: Read + Send + 'static>(reader: R, sender: Sender<WorkerEvent>, prefix: &'static str) {
    thread::spawn(move || {
        let buffered = BufReader::new(reader);
        for line in buffered.lines() {
            match line {
                Ok(content) => {
                    sender
                        .send(WorkerEvent::BackendLogLine(format!("[{prefix}] {content}")))
                        .ok();
                }
                Err(err) => {
                    sender
                        .send(WorkerEvent::BackendLogLine(format!("[{prefix}] 读取日志失败：{err}")))
                        .ok();
                    break;
                }
            }
        }
    });
}

fn detect_backend_dir() -> PathBuf {
    let candidates = {
        let mut result = Vec::new();
        if let Ok(current) = std::env::current_dir() {
            result.push(current.join("../backend"));
            result.push(current.join("backend"));
        }
        if let Ok(exe) = std::env::current_exe() {
            for ancestor in exe.ancestors() {
                result.push(ancestor.join("backend"));
                result.push(ancestor.join("../backend"));
            }
        }
        result
    };

    for candidate in candidates {
        if candidate.is_dir() && candidate.join("pyproject.toml").exists() {
            return candidate.canonicalize().unwrap_or(candidate);
        }
    }

    PathBuf::from("../backend")
}

fn build_markdown_report(
    job: &ReviewJobRead,
    selected_submission: Option<&SubmissionRead>,
    logs: &[SubmissionLogRead],
) -> String {
    let mut lines = vec![
        format!("# {}", job.title),
        String::new(),
        format!("- 状态：{}", job.status),
        format!("- 解析模式：{}", review_mode_label(&job.document_parse_mode)),
        format!("- 评分制式：{} 分", job.score_scale),
        String::new(),
        "## 题目".to_owned(),
        job.question.clone(),
        String::new(),
    ];

    if let Some(rubric) = &job.rubric {
        lines.push("## 评分规则".to_owned());
        lines.push(rubric.clone());
        lines.push(String::new());
    }

    lines.push("## 提交汇总".to_owned());
    lines.push("| 文件 | 学生 | 分数 | 执行状态 | 复核状态 | 总结 |".to_owned());
    lines.push("| --- | --- | --- | --- | --- | --- |".to_owned());
    for submission in &job.submissions {
        lines.push(format!(
            "| {} | {} | {} | {} | {} | {} |",
            submission.original_filename,
            submission.matched_student_name.as_deref().unwrap_or("-"),
            submission
                .score
                .map(|value| format!("{value:.2}/{}", submission.score_scale))
                .unwrap_or_else(|| "-".to_owned()),
            submission.status,
            submission.review_status,
            submission.review_summary.as_deref().unwrap_or("-").replace('\n', " "),
        ));
    }
    lines.push(String::new());

    if let Some(submission) = selected_submission {
        lines.push("## 当前选中提交".to_owned());
        lines.push(format!("- 文件：{}", submission.original_filename));
        lines.push(format!(
            "- 学生：{}",
            submission.matched_student_name.as_deref().unwrap_or("-")
        ));
        lines.push(format!(
            "- 分数：{}",
            submission
                .score
                .map(|value| format!("{value:.2}/{}", submission.score_scale))
                .unwrap_or_else(|| "-".to_owned())
        ));
        lines.push(format!("- 复核状态：{}", submission.review_status));
        if let Some(comment) = &submission.teacher_comment {
            lines.push(format!("- 教师评语：{comment}"));
        }
        lines.push(String::new());
        if !logs.is_empty() {
            lines.push("## 当前选中提交日志".to_owned());
            for log in logs {
                lines.push(format!(
                    "- [{}][{}] {}",
                    log.created_at, log.stage, log.message
                ));
            }
        }
    }

    lines.join("\n")
}
