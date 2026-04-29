use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{Receiver, Sender, channel};
use std::thread;
use std::time::{Duration, Instant};

use eframe::CreationContext;
use eframe::egui::{
    self, Color32, CornerRadius, FontDefinitions, FontFamily, FontId, Margin, RichText, Shadow,
    Stroke, TextEdit, Ui,
};
use rfd::FileDialog;

use crate::api::ApiClient;
use crate::models::{
    AgentRunRead, ApprovalTaskRead, AssignmentCreate, AssignmentRead, AuditEventRead, CourseCreate,
    CourseEnrollmentRead, CourseRead, CourseReviewSummaryRead, DashboardSnapshot, HealthResponse,
    ManualReviewUpdate, NamingPlanCreate, NamingPlanRead, NamingPolicyCreate, NamingPolicyRead,
    ReviewPrepRead, ReviewQuestionItemPatch, ReviewQuestionItemRead, ReviewResultRead,
    ReviewRunCreate, ReviewRunRead, ReviewRuntimeSettingsRead, ReviewRuntimeSettingsUpdate,
    RosterCandidateDecision, RosterCandidateRead, RosterImportBatchRead,
    RosterImportConfirmRequest, SubmissionConfirmDecision, SubmissionImportBatchCreate,
    SubmissionImportBatchRead, SubmissionImportConfirmRequest, SubmissionRead, ToolCallLogRead,
};

const MAX_BACKEND_LOG_LINES: usize = 600;
const CJK_FONT_NAME: &str = "noto_sans_cjk_sc";
const RUNTIME_POLL_INTERVAL: Duration = Duration::from_millis(1200);

const ROSTER_PARSE_MODES: [(&str, &str); 3] = [
    ("auto", "自动"),
    ("local_only", "本地优先"),
    ("agent_vision", "多模态 Agent"),
];

#[derive(Clone, Copy, PartialEq, Eq)]
enum WorkspacePage {
    Overview,
    Summary,
    Courses,
    Assignments,
    Naming,
    ReviewPrep,
    ReviewRun,
    Audit,
    Settings,
}

impl WorkspacePage {
    const ALL: [Self; 9] = [
        Self::Overview,
        Self::Summary,
        Self::Courses,
        Self::Assignments,
        Self::Naming,
        Self::ReviewPrep,
        Self::ReviewRun,
        Self::Audit,
        Self::Settings,
    ];

    fn title(self) -> &'static str {
        match self {
            Self::Overview => "总览",
            Self::Summary => "成绩汇总",
            Self::Courses => "课程与名单",
            Self::Assignments => "作业与提交",
            Self::Naming => "命名与审批",
            Self::ReviewPrep => "评审初始化",
            Self::ReviewRun => "正式评审",
            Self::Audit => "日志审计",
            Self::Settings => "设置",
        }
    }

    fn subtitle(self) -> &'static str {
        match self {
            Self::Overview => "以课程为中心查看当前流程进度。",
            Self::Summary => "按课程查看已发布作业成绩与简评汇总。",
            Self::Courses => "创建课程，导入名单，并确认学生候选。",
            Self::Assignments => "创建单次作业，导入作业目录，并确认匹配关系。",
            Self::Naming => "生成命名计划，查看命令预览，审批后再执行。",
            Self::ReviewPrep => "上传题目/答案/评分规范材料，生成结构化评审基线。",
            Self::ReviewRun => "启动多 Agent 评审，查看结果并进行人工复核。",
            Self::Audit => "查看 Agent 调用、工具调用和课程审计事件。",
            Self::Settings => "后端地址、本地后端进程和运行日志独立管理。",
        }
    }

    fn nav_index(self) -> &'static str {
        match self {
            Self::Overview => "01",
            Self::Summary => "02",
            Self::Courses => "03",
            Self::Assignments => "04",
            Self::Naming => "05",
            Self::ReviewPrep => "06",
            Self::ReviewRun => "07",
            Self::Audit => "08",
            Self::Settings => "09",
        }
    }
}

pub struct AssistantApp {
    backend_url: String,
    health: Option<HealthResponse>,
    courses: Vec<CourseRead>,
    enrollments: Vec<CourseEnrollmentRead>,
    course_review_summary: Option<CourseReviewSummaryRead>,
    assignments: Vec<AssignmentRead>,
    submissions: Vec<SubmissionRead>,
    roster_batch: Option<RosterImportBatchRead>,
    roster_candidates: Vec<RosterCandidateRead>,
    submission_batch: Option<SubmissionImportBatchRead>,
    naming_policies: Vec<NamingPolicyRead>,
    naming_plan: Option<NamingPlanRead>,
    active_approval: Option<ApprovalTaskRead>,
    review_prep: Option<ReviewPrepRead>,
    review_questions: Vec<ReviewQuestionItemRead>,
    review_run: Option<ReviewRunRead>,
    review_results: Vec<ReviewResultRead>,
    agent_runs: Vec<AgentRunRead>,
    tool_calls: Vec<ToolCallLogRead>,
    audit_events: Vec<AuditEventRead>,
    selected_course_id: Option<String>,
    selected_assignment_id: Option<String>,
    selected_policy_id: Option<String>,
    selected_question_id: Option<String>,
    selected_result_id: Option<String>,
    selected_agent_run_id: Option<String>,
    active_page: WorkspacePage,
    status: String,
    pending_tasks: usize,
    course_context_requested_for: Option<String>,
    last_runtime_poll_at: Instant,
    runtime_poll_in_flight: bool,
    event_tx: Sender<WorkerEvent>,
    event_rx: Receiver<WorkerEvent>,
    backend_control: BackendControl,
    course_form: CourseForm,
    roster_form: RosterForm,
    assignment_form: AssignmentForm,
    submission_form: SubmissionForm,
    naming_form: NamingForm,
    review_prep_form: ReviewPrepForm,
    review_run_form: ReviewRunForm,
    review_settings_form: ReviewSettingsForm,
}

struct BackendControl {
    backend_dir: String,
    child: Option<Child>,
    state: String,
    logs: VecDeque<String>,
}

struct CourseForm {
    course_code: String,
    course_name: String,
    term: String,
    class_label: String,
    teacher_name: String,
}

struct RosterForm {
    file_paths: Vec<String>,
    parse_mode: String,
}

struct AssignmentForm {
    seq_no: String,
    title: String,
    description: String,
    due_at: String,
}

#[derive(Default)]
struct SubmissionForm {
    root_path: String,
}

struct NamingForm {
    template_text: String,
    natural_language_rule: String,
    approval_note: String,
}

#[derive(Default)]
struct ReviewPrepForm {
    material_paths: Vec<String>,
    question_text: String,
    answer_short: String,
    answer_full: String,
    rubric: String,
    score_weight: String,
    status: String,
}

struct ReviewRunForm {
    parallelism: String,
    manual_score: String,
    manual_summary: String,
    manual_decision: String,
    publish_note: String,
}

struct ReviewSettingsForm {
    review_prep_max_answer_rounds: String,
    review_run_default_parallelism: String,
    review_run_enable_validation_agent: bool,
    default_review_scale: String,
    submission_unpack_max_depth: String,
    submission_unpack_max_files: String,
    vision_max_assets_per_submission: String,
    llm_timeout_seconds: String,
    llm_max_retries: String,
}

enum WorkerEvent {
    TaskStarted(String),
    TaskFinished(String),
    SnapshotLoaded(DashboardSnapshot),
    CourseCreated(CourseRead),
    EnrollmentsLoaded(Vec<CourseEnrollmentRead>),
    AssignmentsLoaded(Vec<AssignmentRead>),
    RosterBatchLoaded(RosterImportBatchRead),
    RosterCandidatesLoaded(Vec<RosterCandidateRead>),
    SubmissionBatchLoaded(SubmissionImportBatchRead),
    SubmissionsLoaded(Vec<SubmissionRead>),
    NamingPoliciesLoaded(Vec<NamingPolicyRead>),
    NamingPlanLoaded(NamingPlanRead),
    ApprovalLoaded(ApprovalTaskRead),
    ReviewPrepLoaded(ReviewPrepRead),
    ReviewQuestionsLoaded(Vec<ReviewQuestionItemRead>),
    ReviewRunLoaded(ReviewRunRead),
    ReviewResultsLoaded(Vec<ReviewResultRead>),
    ReviewSettingsLoaded(ReviewRuntimeSettingsRead),
    CourseReviewSummaryLoaded(CourseReviewSummaryRead),
    AgentRunsLoaded(Vec<AgentRunRead>),
    ToolCallsLoaded(Vec<ToolCallLogRead>),
    AuditEventsLoaded(Vec<AuditEventRead>),
    BackendLogLine(String),
    RuntimePollFinished,
    Error(String),
}

impl Default for CourseForm {
    fn default() -> Self {
        Self {
            course_code: String::new(),
            course_name: String::new(),
            term: "2026 春季".to_owned(),
            class_label: String::new(),
            teacher_name: String::new(),
        }
    }
}

impl Default for RosterForm {
    fn default() -> Self {
        Self {
            file_paths: Vec::new(),
            parse_mode: "auto".to_owned(),
        }
    }
}

impl Default for AssignmentForm {
    fn default() -> Self {
        Self {
            seq_no: "1".to_owned(),
            title: String::new(),
            description: String::new(),
            due_at: String::new(),
        }
    }
}

impl Default for NamingForm {
    fn default() -> Self {
        Self {
            template_text: "{assignment}_{student_no}_{name}".to_owned(),
            natural_language_rule: "按课程作业序号、学号、姓名统一命名，保留原扩展名。".to_owned(),
            approval_note: String::new(),
        }
    }
}

impl Default for ReviewRunForm {
    fn default() -> Self {
        Self {
            parallelism: String::new(),
            manual_score: "0".to_owned(),
            manual_summary: String::new(),
            manual_decision: "manual_reviewed".to_owned(),
            publish_note: String::new(),
        }
    }
}

impl Default for ReviewSettingsForm {
    fn default() -> Self {
        Self {
            review_prep_max_answer_rounds: "3".to_owned(),
            review_run_default_parallelism: "4".to_owned(),
            review_run_enable_validation_agent: true,
            default_review_scale: "100".to_owned(),
            submission_unpack_max_depth: "4".to_owned(),
            submission_unpack_max_files: "120".to_owned(),
            vision_max_assets_per_submission: "6".to_owned(),
            llm_timeout_seconds: "120".to_owned(),
            llm_max_retries: "2".to_owned(),
        }
    }
}

impl AssistantApp {
    pub fn new(cc: &CreationContext<'_>) -> Self {
        install_cjk_font(&cc.egui_ctx);
        apply_macos_theme(&cc.egui_ctx);
        cc.egui_ctx.set_pixels_per_point(1.12);

        let (event_tx, event_rx) = channel();
        let app = Self {
            backend_url: "http://127.0.0.1:18080".to_owned(),
            health: None,
            courses: Vec::new(),
            enrollments: Vec::new(),
            course_review_summary: None,
            assignments: Vec::new(),
            submissions: Vec::new(),
            roster_batch: None,
            roster_candidates: Vec::new(),
            submission_batch: None,
            naming_policies: Vec::new(),
            naming_plan: None,
            active_approval: None,
            review_prep: None,
            review_questions: Vec::new(),
            review_run: None,
            review_results: Vec::new(),
            agent_runs: Vec::new(),
            tool_calls: Vec::new(),
            audit_events: Vec::new(),
            selected_course_id: None,
            selected_assignment_id: None,
            selected_policy_id: None,
            selected_question_id: None,
            selected_result_id: None,
            selected_agent_run_id: None,
            active_page: WorkspacePage::Overview,
            status: "桌面端已启动，等待连接后端".to_owned(),
            pending_tasks: 0,
            course_context_requested_for: None,
            last_runtime_poll_at: Instant::now() - RUNTIME_POLL_INTERVAL,
            runtime_poll_in_flight: false,
            event_tx,
            event_rx,
            backend_control: BackendControl {
                backend_dir: detect_backend_dir().display().to_string(),
                child: None,
                state: "未托管后端".to_owned(),
                logs: VecDeque::new(),
            },
            course_form: CourseForm::default(),
            roster_form: RosterForm::default(),
            assignment_form: AssignmentForm::default(),
            submission_form: SubmissionForm::default(),
            naming_form: NamingForm::default(),
            review_prep_form: ReviewPrepForm::default(),
            review_run_form: ReviewRunForm::default(),
            review_settings_form: ReviewSettingsForm::default(),
        };
        app.spawn_refresh();
        app
    }

    fn spawn_refresh(&self) {
        self.spawn_task("刷新数据", |api| {
            Ok(vec![WorkerEvent::SnapshotLoaded(api.fetch_snapshot()?)])
        });
    }

    fn has_active_runtime_job(&self) -> bool {
        self.roster_batch
            .as_ref()
            .is_some_and(|batch| is_roster_runtime_active(&batch.status))
            || self
                .submission_batch
                .as_ref()
                .is_some_and(|batch| is_submission_runtime_active(&batch.status))
            || self
                .review_prep
                .as_ref()
                .is_some_and(|prep| is_review_prep_runtime_active(&prep.status))
            || self
                .review_run
                .as_ref()
                .is_some_and(|run| is_review_run_runtime_active(&run.status))
    }

    fn spawn_runtime_poll(&mut self) {
        if self.runtime_poll_in_flight {
            return;
        }
        let roster_batch_id = self
            .roster_batch
            .as_ref()
            .filter(|batch| is_roster_runtime_active(&batch.status))
            .map(|batch| batch.public_id.clone());
        let submission_batch_id = self
            .submission_batch
            .as_ref()
            .filter(|batch| is_submission_runtime_active(&batch.status))
            .map(|batch| batch.public_id.clone());
        let review_prep_id = self
            .review_prep
            .as_ref()
            .filter(|prep| is_review_prep_runtime_active(&prep.status))
            .map(|prep| prep.public_id.clone());
        let review_run_id = self
            .review_run
            .as_ref()
            .filter(|run| is_review_run_runtime_active(&run.status))
            .map(|run| run.public_id.clone());
        if roster_batch_id.is_none()
            && submission_batch_id.is_none()
            && review_prep_id.is_none()
            && review_run_id.is_none()
        {
            return;
        }

        self.runtime_poll_in_flight = true;
        self.last_runtime_poll_at = Instant::now();

        let sender = self.event_tx.clone();
        let base_url = self.backend_url.trim().to_owned();
        thread::spawn(move || {
            let client = match ApiClient::new(base_url) {
                Ok(client) => client,
                Err(err) => {
                    sender.send(WorkerEvent::Error(err)).ok();
                    sender.send(WorkerEvent::RuntimePollFinished).ok();
                    return;
                }
            };

            let result: Result<Vec<WorkerEvent>, String> = (|| {
                let mut events = Vec::new();
                if let Ok(snapshot) = client.fetch_snapshot() {
                    events.push(WorkerEvent::SnapshotLoaded(snapshot));
                }
                if let Some(batch_id) = roster_batch_id {
                    events.push(WorkerEvent::RosterBatchLoaded(
                        client.get_roster_import(&batch_id)?,
                    ));
                    events.push(WorkerEvent::RosterCandidatesLoaded(
                        client.list_roster_candidates(&batch_id).unwrap_or_default(),
                    ));
                }
                if let Some(batch_id) = submission_batch_id {
                    events.push(WorkerEvent::SubmissionBatchLoaded(
                        client.get_submission_import(&batch_id)?,
                    ));
                    events.push(WorkerEvent::SubmissionsLoaded(
                        client.list_batch_submissions(&batch_id).unwrap_or_default(),
                    ));
                }
                if let Some(prep_id) = review_prep_id {
                    events.push(WorkerEvent::ReviewPrepLoaded(
                        client.get_review_prep(&prep_id)?,
                    ));
                    events.push(WorkerEvent::ReviewQuestionsLoaded(
                        client.list_review_questions(&prep_id).unwrap_or_default(),
                    ));
                }
                if let Some(run_id) = review_run_id {
                    events.push(WorkerEvent::ReviewRunLoaded(
                        client.get_review_run(&run_id)?,
                    ));
                    events.push(WorkerEvent::ReviewResultsLoaded(
                        client.list_review_results(&run_id).unwrap_or_default(),
                    ));
                }
                Ok(events)
            })();

            match result {
                Ok(events) => {
                    for event in events {
                        sender.send(event).ok();
                    }
                }
                Err(err) => {
                    sender.send(WorkerEvent::Error(err)).ok();
                }
            }
            sender.send(WorkerEvent::RuntimePollFinished).ok();
        });
    }

    fn spawn_load_review_settings(&self) {
        self.spawn_task("加载评审设置", |api| {
            Ok(vec![WorkerEvent::ReviewSettingsLoaded(
                api.get_review_settings()?,
            )])
        });
    }

    fn spawn_create_course(&self) {
        if self.course_form.course_code.trim().is_empty()
            || self.course_form.course_name.trim().is_empty()
        {
            self.send_error("课程编号和课程名称不能为空。");
            return;
        }
        let payload = CourseCreate {
            course_code: self.course_form.course_code.trim().to_owned(),
            course_name: self.course_form.course_name.trim().to_owned(),
            term: self.course_form.term.trim().to_owned(),
            class_label: self.course_form.class_label.trim().to_owned(),
            teacher_name: trimmed_option(&self.course_form.teacher_name),
        };
        self.spawn_task("创建课程", move |api| {
            let course = api.create_course(&payload)?;
            let snapshot = api.fetch_snapshot()?;
            Ok(vec![
                WorkerEvent::CourseCreated(course),
                WorkerEvent::SnapshotLoaded(snapshot),
            ])
        });
    }

    fn spawn_load_course_context(&self) {
        let Some(course_id) = self.selected_course_id.clone() else {
            return;
        };
        self.spawn_task("加载课程上下文", move |api| {
            Ok(vec![
                WorkerEvent::EnrollmentsLoaded(api.list_enrollments(&course_id)?),
                WorkerEvent::CourseReviewSummaryLoaded(api.get_course_review_summary(&course_id)?),
                WorkerEvent::AssignmentsLoaded(api.list_assignments(&course_id)?),
                WorkerEvent::AuditEventsLoaded(
                    api.list_course_audit_events(&course_id).unwrap_or_default(),
                ),
            ])
        });
    }

    fn spawn_load_course_review_summary(&self) {
        let Some(course_id) = self.selected_course_id.clone() else {
            self.send_error("请先选择课程。");
            return;
        };
        self.spawn_task("加载成绩汇总", move |api| {
            Ok(vec![WorkerEvent::CourseReviewSummaryLoaded(
                api.get_course_review_summary(&course_id)?,
            )])
        });
    }

    fn spawn_create_roster_import(&self) {
        let Some(course_id) = self.selected_course_id.clone() else {
            self.send_error("请先选择课程。");
            return;
        };
        if self.roster_form.file_paths.is_empty() {
            self.send_error("请先选择名单文件。");
            return;
        }
        let files = self.roster_form.file_paths.clone();
        let parse_mode = self.roster_form.parse_mode.clone();
        self.spawn_task("创建名单导入", move |api| {
            let batch = api.create_roster_import(&course_id, &files, &parse_mode)?;
            Ok(vec![WorkerEvent::RosterBatchLoaded(batch)])
        });
    }

    fn spawn_run_roster_import(&self) {
        let Some(batch_id) = self
            .roster_batch
            .as_ref()
            .map(|batch| batch.public_id.clone())
        else {
            self.send_error("请先创建名单导入批次。");
            return;
        };
        self.spawn_task("运行初始化 Agent", move |api| {
            Ok(vec![WorkerEvent::RosterBatchLoaded(
                api.run_roster_import(&batch_id)?,
            )])
        });
    }

    fn spawn_cancel_roster_import(&self) {
        let Some(batch_id) = self
            .roster_batch
            .as_ref()
            .map(|batch| batch.public_id.clone())
        else {
            self.send_error("当前没有可停止的名单初始化任务。");
            return;
        };
        self.spawn_task("停止初始化 Agent", move |api| {
            Ok(vec![WorkerEvent::RosterBatchLoaded(
                api.cancel_roster_import(&batch_id)?,
            )])
        });
    }

    fn spawn_confirm_roster_import(&self) {
        let Some(batch_id) = self
            .roster_batch
            .as_ref()
            .map(|batch| batch.public_id.clone())
        else {
            self.send_error("请先运行名单初始化 Agent。");
            return;
        };
        if self.roster_candidates.is_empty() {
            self.send_error("当前没有可确认的名单候选。");
            return;
        }
        let payload = RosterImportConfirmRequest {
            items: self
                .roster_candidates
                .iter()
                .map(|candidate| RosterCandidateDecision {
                    candidate_public_id: candidate.public_id.clone(),
                    decision_status: "accepted".to_owned(),
                    student_no: candidate.student_no.clone(),
                    name: Some(candidate.name.clone()),
                    decision_note: Some("桌面端批量接受".to_owned()),
                })
                .collect(),
        };
        self.spawn_task("确认名单候选", move |api| {
            Ok(vec![WorkerEvent::RosterBatchLoaded(
                api.confirm_roster_import(&batch_id, &payload)?,
            )])
        });
    }

    fn spawn_apply_roster_import(&self) {
        let Some(batch_id) = self
            .roster_batch
            .as_ref()
            .map(|batch| batch.public_id.clone())
        else {
            self.send_error("请先确认名单候选。");
            return;
        };
        self.spawn_task("应用课程名单", move |api| {
            let batch = api.apply_roster_import(&batch_id)?;
            let course_id = batch.course_public_id.clone();
            Ok(vec![
                WorkerEvent::RosterBatchLoaded(batch),
                WorkerEvent::EnrollmentsLoaded(api.list_enrollments(&course_id)?),
                WorkerEvent::SnapshotLoaded(api.fetch_snapshot()?),
            ])
        });
    }

    fn spawn_create_assignment(&self) {
        let Some(course_id) = self.selected_course_id.clone() else {
            self.send_error("请先选择课程。");
            return;
        };
        let seq_no = match self.assignment_form.seq_no.trim().parse::<i64>() {
            Ok(value) => value,
            Err(_) => {
                self.send_error("作业序号必须是整数。");
                return;
            }
        };
        if self.assignment_form.title.trim().is_empty() {
            self.send_error("作业标题不能为空。");
            return;
        }
        let payload = AssignmentCreate {
            seq_no,
            title: self.assignment_form.title.trim().to_owned(),
            description: trimmed_option(&self.assignment_form.description),
            due_at: trimmed_option(&self.assignment_form.due_at),
        };
        self.spawn_task("创建作业", move |api| {
            let assignment = api.create_assignment(&course_id, &payload)?;
            Ok(vec![
                WorkerEvent::AssignmentsLoaded(api.list_assignments(&course_id)?),
                WorkerEvent::SubmissionsLoaded(
                    api.list_assignment_submissions(&assignment.public_id)
                        .unwrap_or_default(),
                ),
            ])
        });
    }

    fn spawn_load_assignment_context(&self) {
        let Some(assignment_id) = self.selected_assignment_id.clone() else {
            return;
        };
        let review_prep_id = self
            .selected_assignment()
            .and_then(|assignment| assignment.review_prep_public_id.clone());
        self.spawn_task("加载作业上下文", move |api| {
            let mut events = vec![
                WorkerEvent::SubmissionsLoaded(api.list_assignment_submissions(&assignment_id)?),
                WorkerEvent::NamingPoliciesLoaded(
                    api.list_naming_policies(&assignment_id).unwrap_or_default(),
                ),
            ];
            if let Some(prep_id) = review_prep_id {
                if let Ok(prep) = api.get_review_prep(&prep_id) {
                    events.push(WorkerEvent::ReviewPrepLoaded(prep));
                }
                if let Ok(questions) = api.list_review_questions(&prep_id) {
                    events.push(WorkerEvent::ReviewQuestionsLoaded(questions));
                }
            }
            Ok(events)
        });
    }

    fn spawn_create_submission_import(&self) {
        let Some(assignment_id) = self.selected_assignment_id.clone() else {
            self.send_error("请先选择作业。");
            return;
        };
        if self.submission_form.root_path.trim().is_empty() {
            self.send_error("请选择作业文件夹。");
            return;
        }
        let payload = SubmissionImportBatchCreate {
            root_path: self.submission_form.root_path.trim().to_owned(),
        };
        self.spawn_task("创建作业导入", move |api| {
            let batch = api.create_submission_import(&assignment_id, &payload)?;
            Ok(vec![WorkerEvent::SubmissionBatchLoaded(batch)])
        });
    }

    fn spawn_run_submission_import(&self) {
        let Some(batch_id) = self
            .submission_batch
            .as_ref()
            .map(|batch| batch.public_id.clone())
        else {
            self.send_error("请先创建作业导入批次。");
            return;
        };
        self.spawn_task("运行导入 Agent", move |api| {
            Ok(vec![WorkerEvent::SubmissionBatchLoaded(
                api.run_submission_import(&batch_id)?,
            )])
        });
    }

    fn spawn_cancel_submission_import(&self) {
        let Some(batch_id) = self
            .submission_batch
            .as_ref()
            .map(|batch| batch.public_id.clone())
        else {
            self.send_error("当前没有可停止的作业导入任务。");
            return;
        };
        self.spawn_task("停止导入 Agent", move |api| {
            Ok(vec![WorkerEvent::SubmissionBatchLoaded(
                api.cancel_submission_import(&batch_id)?,
            )])
        });
    }

    fn spawn_confirm_submission_import(&self) {
        let Some(batch_id) = self
            .submission_batch
            .as_ref()
            .map(|batch| batch.public_id.clone())
        else {
            self.send_error("请先运行作业导入 Agent。");
            return;
        };
        if self.submissions.is_empty() {
            self.send_error("当前没有可确认的提交记录。");
            return;
        }
        let payload = SubmissionImportConfirmRequest {
            items: self
                .submissions
                .iter()
                .map(|submission| SubmissionConfirmDecision {
                    submission_public_id: submission.public_id.clone(),
                    enrollment_public_id: submission.enrollment_public_id.clone(),
                    status: Some(
                        if submission.enrollment_public_id.is_some() {
                            "confirmed"
                        } else {
                            "unmatched"
                        }
                        .to_owned(),
                    ),
                    note: Some("桌面端按 Agent 匹配结果确认".to_owned()),
                })
                .collect(),
        };
        self.spawn_task("确认作业匹配", move |api| {
            Ok(vec![WorkerEvent::SubmissionBatchLoaded(
                api.confirm_submission_import(&batch_id, &payload)?,
            )])
        });
    }

    fn spawn_apply_submission_import(&self) {
        let Some(batch_id) = self
            .submission_batch
            .as_ref()
            .map(|batch| batch.public_id.clone())
        else {
            self.send_error("请先确认作业匹配。");
            return;
        };
        self.spawn_task("应用作业导入", move |api| {
            let batch = api.apply_submission_import(&batch_id)?;
            let submissions = api.list_assignment_submissions(&batch.assignment_public_id)?;
            Ok(vec![
                WorkerEvent::SubmissionBatchLoaded(batch),
                WorkerEvent::SubmissionsLoaded(submissions),
            ])
        });
    }

    fn spawn_create_naming_policy(&self) {
        let Some(assignment_id) = self.selected_assignment_id.clone() else {
            self.send_error("请先选择作业。");
            return;
        };
        let payload = NamingPolicyCreate {
            template_text: trimmed_option(&self.naming_form.template_text),
            natural_language_rule: trimmed_option(&self.naming_form.natural_language_rule),
        };
        self.spawn_task("创建命名策略", move |api| {
            api.create_naming_policy(&assignment_id, &payload)?;
            Ok(vec![WorkerEvent::NamingPoliciesLoaded(
                api.list_naming_policies(&assignment_id)?,
            )])
        });
    }

    fn spawn_create_naming_plan(&self) {
        let Some(assignment_id) = self.selected_assignment_id.clone() else {
            self.send_error("请先选择作业。");
            return;
        };
        let payload = NamingPlanCreate {
            policy_public_id: self.selected_policy_id.clone(),
            template_text: trimmed_option(&self.naming_form.template_text),
            natural_language_rule: trimmed_option(&self.naming_form.natural_language_rule),
        };
        self.spawn_task("生成命名计划", move |api| {
            Ok(vec![WorkerEvent::NamingPlanLoaded(
                api.create_naming_plan(&assignment_id, &payload)?,
            )])
        });
    }

    fn spawn_submit_naming_approval(&self) {
        let Some(plan_id) = self.naming_plan.as_ref().map(|plan| plan.public_id.clone()) else {
            self.send_error("请先生成命名计划。");
            return;
        };
        self.spawn_task("提交命名审批", move |api| {
            let task = api.submit_naming_plan_approval(&plan_id)?;
            let plan = api.get_naming_plan(&plan_id)?;
            Ok(vec![
                WorkerEvent::ApprovalLoaded(task),
                WorkerEvent::NamingPlanLoaded(plan),
            ])
        });
    }

    fn spawn_approve_active_task(&self) {
        let Some(task_id) = self
            .active_approval
            .as_ref()
            .map(|task| task.public_id.clone())
        else {
            self.send_error("当前没有审批任务。");
            return;
        };
        let note = trimmed_option(&self.naming_form.approval_note)
            .or_else(|| trimmed_option(&self.review_run_form.publish_note));
        self.spawn_task("批准审批任务", move |api| {
            Ok(vec![WorkerEvent::ApprovalLoaded(
                api.approve_task(&task_id, note)?,
            )])
        });
    }

    fn spawn_reject_active_task(&self) {
        let Some(task_id) = self
            .active_approval
            .as_ref()
            .map(|task| task.public_id.clone())
        else {
            self.send_error("当前没有审批任务。");
            return;
        };
        let note = trimmed_option(&self.naming_form.approval_note)
            .or_else(|| trimmed_option(&self.review_run_form.publish_note));
        self.spawn_task("拒绝审批任务", move |api| {
            Ok(vec![WorkerEvent::ApprovalLoaded(
                api.reject_task(&task_id, note)?,
            )])
        });
    }

    fn spawn_execute_naming_plan(&self) {
        let Some(plan_id) = self.naming_plan.as_ref().map(|plan| plan.public_id.clone()) else {
            self.send_error("请先生成并审批命名计划。");
            return;
        };
        self.spawn_task("执行命名计划", move |api| {
            let plan = api.execute_naming_plan(&plan_id)?;
            let submissions = api
                .list_assignment_submissions(&plan.assignment_public_id)
                .unwrap_or_default();
            Ok(vec![
                WorkerEvent::NamingPlanLoaded(plan),
                WorkerEvent::SubmissionsLoaded(submissions),
            ])
        });
    }

    fn spawn_rollback_naming_plan(&self) {
        let Some(plan_id) = self.naming_plan.as_ref().map(|plan| plan.public_id.clone()) else {
            self.send_error("当前没有可回滚的命名计划。");
            return;
        };
        self.spawn_task("回滚命名计划", move |api| {
            Ok(vec![WorkerEvent::NamingPlanLoaded(
                api.rollback_naming_plan(&plan_id)?,
            )])
        });
    }

    fn spawn_create_review_prep(&self) {
        let Some(assignment_id) = self.selected_assignment_id.clone() else {
            self.send_error("请先选择作业。");
            return;
        };
        if self.review_prep_form.material_paths.is_empty() {
            self.send_error("请先选择评审初始化材料。");
            return;
        }
        let files = self.review_prep_form.material_paths.clone();
        self.spawn_task("创建评审初始化", move |api| {
            Ok(vec![WorkerEvent::ReviewPrepLoaded(
                api.create_review_prep(&assignment_id, &files)?,
            )])
        });
    }

    fn spawn_run_review_prep(&self) {
        let Some(prep_id) = self.review_prep.as_ref().map(|prep| prep.public_id.clone()) else {
            self.send_error("请先创建评审初始化版本。");
            return;
        };
        self.spawn_task("运行评审初始化 Agent", move |api| {
            Ok(vec![WorkerEvent::ReviewPrepLoaded(
                api.run_review_prep(&prep_id)?,
            )])
        });
    }

    fn spawn_cancel_review_prep(&self) {
        let Some(prep_id) = self.review_prep.as_ref().map(|prep| prep.public_id.clone()) else {
            self.send_error("当前没有可停止的评审初始化任务。");
            return;
        };
        self.spawn_task("停止评审初始化 Agent", move |api| {
            Ok(vec![WorkerEvent::ReviewPrepLoaded(
                api.cancel_review_prep(&prep_id)?,
            )])
        });
    }

    fn spawn_patch_review_question(&self) {
        let Some(item_id) = self.selected_question_id.clone() else {
            self.send_error("请先选择题目项。");
            return;
        };
        let score_weight = match trimmed_option(&self.review_prep_form.score_weight) {
            Some(value) => match value.parse::<f32>() {
                Ok(parsed) => Some(parsed),
                Err(_) => {
                    self.send_error("分值权重必须是数字。");
                    return;
                }
            },
            None => None,
        };
        let payload = ReviewQuestionItemPatch {
            question_full_text: trimmed_option(&self.review_prep_form.question_text),
            reference_answer_short: trimmed_option(&self.review_prep_form.answer_short),
            reference_answer_full: trimmed_option(&self.review_prep_form.answer_full),
            rubric_text: trimmed_option(&self.review_prep_form.rubric),
            score_weight,
            status: trimmed_option(&self.review_prep_form.status),
        };
        let prep_id = self.review_prep.as_ref().map(|prep| prep.public_id.clone());
        self.spawn_task("保存题目项", move |api| {
            let item = api.patch_review_question(&item_id, &payload)?;
            let mut events = Vec::new();
            if let Some(prep_id) = prep_id {
                events.push(WorkerEvent::ReviewQuestionsLoaded(
                    api.list_review_questions(&prep_id)?,
                ));
            }
            events.push(WorkerEvent::ReviewQuestionsLoaded(vec![item]));
            Ok(events)
        });
    }

    fn spawn_confirm_review_prep(&self) {
        let Some(prep_id) = self.review_prep.as_ref().map(|prep| prep.public_id.clone()) else {
            self.send_error("请先运行评审初始化 Agent。");
            return;
        };
        self.spawn_task("确认评审初始化", move |api| {
            let prep = api.confirm_review_prep(&prep_id)?;
            let snapshot = api.fetch_snapshot()?;
            Ok(vec![
                WorkerEvent::ReviewPrepLoaded(prep),
                WorkerEvent::SnapshotLoaded(snapshot),
            ])
        });
    }

    fn spawn_create_review_run(&self) {
        let Some(assignment_id) = self.selected_assignment_id.clone() else {
            self.send_error("请先选择作业。");
            return;
        };
        let parallelism = match trimmed_option(&self.review_run_form.parallelism) {
            Some(value) => match value.parse::<i64>() {
                Ok(parsed) => Some(parsed),
                Err(_) => {
                    self.send_error("并行数必须是整数。");
                    return;
                }
            },
            None => None,
        };
        let payload = ReviewRunCreate {
            review_prep_public_id: self.review_prep.as_ref().map(|prep| prep.public_id.clone()),
            parallelism,
        };
        self.spawn_task("创建评审运行", move |api| {
            Ok(vec![WorkerEvent::ReviewRunLoaded(
                api.create_review_run(&assignment_id, &payload)?,
            )])
        });
    }

    fn spawn_save_review_settings(&self) {
        let review_prep_max_answer_rounds = match parse_i64_setting(
            &self.review_settings_form.review_prep_max_answer_rounds,
            "评审初始化最大轮数",
        ) {
            Ok(value) => value,
            Err(message) => {
                self.send_error(&message);
                return;
            }
        };
        let review_run_default_parallelism = match parse_i64_setting(
            &self.review_settings_form.review_run_default_parallelism,
            "默认并行数",
        ) {
            Ok(value) => value,
            Err(message) => {
                self.send_error(&message);
                return;
            }
        };
        let default_review_scale =
            match parse_i64_setting(&self.review_settings_form.default_review_scale, "默认总分")
            {
                Ok(value) => value,
                Err(message) => {
                    self.send_error(&message);
                    return;
                }
            };
        let submission_unpack_max_depth = match parse_i64_setting(
            &self.review_settings_form.submission_unpack_max_depth,
            "压缩包递归深度",
        ) {
            Ok(value) => value,
            Err(message) => {
                self.send_error(&message);
                return;
            }
        };
        let submission_unpack_max_files = match parse_i64_setting(
            &self.review_settings_form.submission_unpack_max_files,
            "压缩包最大文件数",
        ) {
            Ok(value) => value,
            Err(message) => {
                self.send_error(&message);
                return;
            }
        };
        let vision_max_assets_per_submission = match parse_i64_setting(
            &self.review_settings_form.vision_max_assets_per_submission,
            "每份作业图片上限",
        ) {
            Ok(value) => value,
            Err(message) => {
                self.send_error(&message);
                return;
            }
        };
        let llm_timeout_seconds = match parse_f64_setting(
            &self.review_settings_form.llm_timeout_seconds,
            "模型请求超时",
        ) {
            Ok(value) => value,
            Err(message) => {
                self.send_error(&message);
                return;
            }
        };
        let llm_max_retries = match parse_i64_setting(
            &self.review_settings_form.llm_max_retries,
            "模型请求重试次数",
        ) {
            Ok(value) => value,
            Err(message) => {
                self.send_error(&message);
                return;
            }
        };
        let payload = ReviewRuntimeSettingsUpdate {
            review_prep_max_answer_rounds,
            review_run_enable_validation_agent: self
                .review_settings_form
                .review_run_enable_validation_agent,
            review_run_default_parallelism,
            default_review_scale,
            submission_unpack_max_depth,
            submission_unpack_max_files,
            vision_max_assets_per_submission,
            llm_timeout_seconds,
            llm_max_retries,
        };
        self.spawn_task("保存评审设置", move |api| {
            let settings = api.update_review_settings(&payload)?;
            let snapshot = api.fetch_snapshot()?;
            Ok(vec![
                WorkerEvent::ReviewSettingsLoaded(settings),
                WorkerEvent::SnapshotLoaded(snapshot),
            ])
        });
    }

    fn spawn_start_review_run(&self) {
        let Some(run_id) = self.review_run.as_ref().map(|run| run.public_id.clone()) else {
            self.send_error("请先创建评审运行。");
            return;
        };
        self.spawn_task("启动正式评审", move |api| {
            Ok(vec![WorkerEvent::ReviewRunLoaded(
                api.start_review_run(&run_id)?,
            )])
        });
    }

    fn spawn_cancel_review_run(&self) {
        let Some(run_id) = self.review_run.as_ref().map(|run| run.public_id.clone()) else {
            self.send_error("当前没有可停止的正式评审任务。");
            return;
        };
        self.spawn_task("停止正式评审", move |api| {
            Ok(vec![WorkerEvent::ReviewRunLoaded(
                api.cancel_review_run(&run_id)?,
            )])
        });
    }

    fn spawn_refresh_review_results(&self) {
        let Some(run_id) = self.review_run.as_ref().map(|run| run.public_id.clone()) else {
            self.send_error("当前没有评审运行。");
            return;
        };
        self.spawn_task("刷新评审结果", move |api| {
            Ok(vec![
                WorkerEvent::ReviewRunLoaded(api.get_review_run(&run_id)?),
                WorkerEvent::ReviewResultsLoaded(api.list_review_results(&run_id)?),
            ])
        });
    }

    fn spawn_retry_review_run(&self) {
        let Some(run_id) = self.review_run.as_ref().map(|run| run.public_id.clone()) else {
            self.send_error("当前没有评审运行。");
            return;
        };
        self.spawn_task("重试需人工处理项", move |api| {
            Ok(vec![WorkerEvent::ReviewRunLoaded(
                api.retry_review_run(&run_id)?,
            )])
        });
    }

    fn spawn_publish_review_run(&self) {
        let Some(run_id) = self.review_run.as_ref().map(|run| run.public_id.clone()) else {
            self.send_error("当前没有评审运行。");
            return;
        };
        self.spawn_task("提交发布审批", move |api| {
            Ok(vec![WorkerEvent::ApprovalLoaded(
                api.publish_review_run(&run_id)?,
            )])
        });
    }

    fn spawn_execute_active_approval(&self) {
        let Some(task_id) = self
            .active_approval
            .as_ref()
            .map(|task| task.public_id.clone())
        else {
            self.send_error("当前没有审批任务。");
            return;
        };
        let course_id = self.selected_course_id.clone();
        let review_run_id = self
            .active_approval
            .as_ref()
            .filter(|task| task.object_type == "review_run")
            .map(|task| task.object_public_id.clone());
        self.spawn_task("执行审批副作用", move |api| {
            let approval = api.execute_approval_task(&task_id)?;
            let mut events = vec![WorkerEvent::ApprovalLoaded(approval)];
            if let Some(run_id) = review_run_id {
                events.push(WorkerEvent::ReviewRunLoaded(api.get_review_run(&run_id)?));
                events.push(WorkerEvent::ReviewResultsLoaded(
                    api.list_review_results(&run_id)?,
                ));
            }
            if let Some(course_id) = course_id {
                events.push(WorkerEvent::CourseReviewSummaryLoaded(
                    api.get_course_review_summary(&course_id)?,
                ));
                events.push(WorkerEvent::AssignmentsLoaded(
                    api.list_assignments(&course_id)?,
                ));
            }
            Ok(events)
        });
    }

    fn spawn_manual_review_result(&self) {
        let Some(result_id) = self.selected_result_id.clone() else {
            self.send_error("请先选择评审结果。");
            return;
        };
        let score = match self.review_run_form.manual_score.trim().parse::<f32>() {
            Ok(value) => value,
            Err(_) => {
                self.send_error("人工复核分数必须是数字。");
                return;
            }
        };
        if self.review_run_form.manual_summary.trim().is_empty() {
            self.send_error("人工复核说明不能为空。");
            return;
        }
        let payload = ManualReviewUpdate {
            total_score: score,
            summary: self.review_run_form.manual_summary.trim().to_owned(),
            decision: self.review_run_form.manual_decision.trim().to_owned(),
        };
        let run_id = self.review_run.as_ref().map(|run| run.public_id.clone());
        self.spawn_task("保存人工复核", move |api| {
            api.manual_review_result(&result_id, &payload)?;
            let mut events = Vec::new();
            if let Some(run_id) = run_id {
                events.push(WorkerEvent::ReviewResultsLoaded(
                    api.list_review_results(&run_id)?,
                ));
            }
            Ok(events)
        });
    }

    fn spawn_load_audit(&self) {
        let course_id = self.selected_course_id.clone();
        self.spawn_task("加载审计日志", move |api| {
            let mut events = vec![WorkerEvent::AgentRunsLoaded(api.list_agent_runs()?)];
            if let Some(course_id) = course_id {
                events.push(WorkerEvent::AuditEventsLoaded(
                    api.list_course_audit_events(&course_id).unwrap_or_default(),
                ));
            }
            Ok(events)
        });
    }

    fn spawn_load_tool_calls(&self) {
        let Some(run_id) = self.selected_agent_run_id.clone() else {
            self.send_error("请先选择 Agent 调用记录。");
            return;
        };
        self.spawn_task("加载工具调用", move |api| {
            Ok(vec![WorkerEvent::ToolCallsLoaded(
                api.list_tool_calls(&run_id)?,
            )])
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
                    sender
                        .send(WorkerEvent::TaskFinished(label.to_owned()))
                        .ok();
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
            sender
                .send(WorkerEvent::TaskFinished(label.to_owned()))
                .ok();
        });
    }

    fn send_error(&self, message: &str) {
        self.event_tx
            .send(WorkerEvent::Error(message.to_owned()))
            .ok();
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
        let mut child = match Command::new("uv")
            .arg("run")
            .arg("backend")
            .current_dir(&backend_dir)
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

    fn schedule_runtime_poll_now(&mut self) {
        self.last_runtime_poll_at = Instant::now() - RUNTIME_POLL_INTERVAL;
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
                WorkerEvent::CourseCreated(course) => {
                    self.selected_course_id = Some(course.public_id);
                    self.course_context_requested_for = None;
                }
                WorkerEvent::EnrollmentsLoaded(items) => self.enrollments = items,
                WorkerEvent::CourseReviewSummaryLoaded(summary) => {
                    self.course_review_summary = Some(summary)
                }
                WorkerEvent::AssignmentsLoaded(items) => self.apply_assignments(items),
                WorkerEvent::RosterBatchLoaded(batch) => {
                    if is_roster_runtime_active(&batch.status) {
                        self.schedule_runtime_poll_now();
                    }
                    self.roster_batch = Some(batch);
                }
                WorkerEvent::RosterCandidatesLoaded(items) => self.roster_candidates = items,
                WorkerEvent::SubmissionBatchLoaded(batch) => {
                    if is_submission_runtime_active(&batch.status) {
                        self.schedule_runtime_poll_now();
                    }
                    self.submission_batch = Some(batch);
                }
                WorkerEvent::SubmissionsLoaded(items) => self.submissions = items,
                WorkerEvent::NamingPoliciesLoaded(items) => self.apply_policies(items),
                WorkerEvent::NamingPlanLoaded(plan) => self.naming_plan = Some(plan),
                WorkerEvent::ApprovalLoaded(task) => self.active_approval = Some(task),
                WorkerEvent::ReviewPrepLoaded(prep) => {
                    if is_review_prep_runtime_active(&prep.status) {
                        self.schedule_runtime_poll_now();
                    }
                    self.review_prep = Some(prep);
                }
                WorkerEvent::ReviewQuestionsLoaded(items) => self.apply_review_questions(items),
                WorkerEvent::ReviewRunLoaded(run) => {
                    if is_review_run_runtime_active(&run.status) {
                        self.schedule_runtime_poll_now();
                    }
                    self.review_run = Some(run);
                }
                WorkerEvent::ReviewResultsLoaded(items) => self.apply_review_results(items),
                WorkerEvent::ReviewSettingsLoaded(settings) => self.apply_review_settings(settings),
                WorkerEvent::AgentRunsLoaded(items) => self.apply_agent_runs(items),
                WorkerEvent::ToolCallsLoaded(items) => self.tool_calls = items,
                WorkerEvent::AuditEventsLoaded(items) => self.audit_events = items,
                WorkerEvent::BackendLogLine(line) => self.push_backend_log(&line),
                WorkerEvent::RuntimePollFinished => self.runtime_poll_in_flight = false,
                WorkerEvent::Error(err) => self.status = err,
            }
        }
    }

    fn apply_snapshot(&mut self, snapshot: DashboardSnapshot) {
        if let Some(health) = snapshot.health.clone() {
            self.apply_review_settings(health.review_runtime_settings.clone());
        }
        self.health = snapshot.health;
        self.courses = snapshot.courses;
        if self.selected_course_id.is_none() || self.selected_course().is_none() {
            self.selected_course_id = self.courses.first().map(|course| course.public_id.clone());
        }
        if let Some(course_id) = self.selected_course_id.clone()
            && self.course_context_requested_for.as_ref() != Some(&course_id)
            && !self.has_active_runtime_job()
        {
            self.course_context_requested_for = Some(course_id);
            self.spawn_load_course_context();
        }
    }

    fn apply_review_settings(&mut self, settings: ReviewRuntimeSettingsRead) {
        self.review_settings_form.review_prep_max_answer_rounds =
            settings.review_prep_max_answer_rounds.to_string();
        self.review_settings_form.review_run_default_parallelism =
            settings.review_run_default_parallelism.to_string();
        self.review_settings_form.review_run_enable_validation_agent =
            settings.review_run_enable_validation_agent;
        self.review_settings_form.default_review_scale = settings.default_review_scale.to_string();
        self.review_settings_form.submission_unpack_max_depth =
            settings.submission_unpack_max_depth.to_string();
        self.review_settings_form.submission_unpack_max_files =
            settings.submission_unpack_max_files.to_string();
        self.review_settings_form.vision_max_assets_per_submission =
            settings.vision_max_assets_per_submission.to_string();
        self.review_settings_form.llm_timeout_seconds =
            format_compact_f64(settings.llm_timeout_seconds);
        self.review_settings_form.llm_max_retries = settings.llm_max_retries.to_string();
    }

    fn apply_assignments(&mut self, assignments: Vec<AssignmentRead>) {
        self.assignments = assignments;
        if self.selected_assignment_id.is_none() || self.selected_assignment().is_none() {
            self.selected_assignment_id = self
                .assignments
                .first()
                .map(|assignment| assignment.public_id.clone());
        }
    }

    fn apply_policies(&mut self, policies: Vec<NamingPolicyRead>) {
        self.naming_policies = policies;
        if self.selected_policy_id.is_none()
            || !self
                .naming_policies
                .iter()
                .any(|policy| Some(&policy.public_id) == self.selected_policy_id.as_ref())
        {
            self.selected_policy_id = self
                .naming_policies
                .first()
                .map(|policy| policy.public_id.clone());
        }
    }

    fn apply_review_questions(&mut self, items: Vec<ReviewQuestionItemRead>) {
        if items.len() == 1 && !self.review_questions.is_empty() {
            let item = items.into_iter().next().unwrap();
            if let Some(existing) = self
                .review_questions
                .iter_mut()
                .find(|existing| existing.public_id == item.public_id)
            {
                *existing = item;
            }
            return;
        }
        self.review_questions = items;
        if self.selected_question_id.is_none() || self.selected_question().is_none() {
            self.selected_question_id = self
                .review_questions
                .first()
                .map(|item| item.public_id.clone());
            self.sync_question_form();
        }
    }

    fn apply_review_results(&mut self, items: Vec<ReviewResultRead>) {
        self.review_results = items;
        if self.selected_result_id.is_none() || self.selected_result().is_none() {
            self.selected_result_id = self
                .review_results
                .first()
                .map(|item| item.public_id.clone());
            self.sync_result_form();
        }
    }

    fn apply_agent_runs(&mut self, items: Vec<AgentRunRead>) {
        self.agent_runs = items;
        if self.selected_agent_run_id.is_none() || self.selected_agent_run().is_none() {
            self.selected_agent_run_id = self.agent_runs.first().map(|run| run.public_id.clone());
        }
    }

    fn selected_course(&self) -> Option<&CourseRead> {
        self.courses
            .iter()
            .find(|course| Some(&course.public_id) == self.selected_course_id.as_ref())
    }

    fn selected_assignment(&self) -> Option<&AssignmentRead> {
        self.assignments
            .iter()
            .find(|assignment| Some(&assignment.public_id) == self.selected_assignment_id.as_ref())
    }

    fn selected_question(&self) -> Option<&ReviewQuestionItemRead> {
        self.review_questions
            .iter()
            .find(|item| Some(&item.public_id) == self.selected_question_id.as_ref())
    }

    fn selected_result(&self) -> Option<&ReviewResultRead> {
        self.review_results
            .iter()
            .find(|item| Some(&item.public_id) == self.selected_result_id.as_ref())
    }

    fn selected_agent_run(&self) -> Option<&AgentRunRead> {
        self.agent_runs
            .iter()
            .find(|run| Some(&run.public_id) == self.selected_agent_run_id.as_ref())
    }

    fn sync_question_form(&mut self) {
        if let Some(item) = self.selected_question().cloned() {
            self.review_prep_form.question_text = item.question_full_text;
            self.review_prep_form.answer_short = item.reference_answer_short.unwrap_or_default();
            self.review_prep_form.answer_full = item.reference_answer_full.unwrap_or_default();
            self.review_prep_form.rubric = item.rubric_text.unwrap_or_default();
            self.review_prep_form.score_weight = format!("{}", item.score_weight);
            self.review_prep_form.status = item.status;
        }
    }

    fn sync_result_form(&mut self) {
        if let Some(result) = self.selected_result().cloned() {
            self.review_run_form.manual_score = result
                .total_score
                .map(|score| format!("{score:.2}"))
                .unwrap_or_else(|| "0".to_owned());
            self.review_run_form.manual_summary = result.summary.unwrap_or_default();
            self.review_run_form.manual_decision = result
                .decision
                .unwrap_or_else(|| "manual_reviewed".to_owned());
        }
    }

    fn choose_roster_files(&mut self) {
        if let Some(paths) = FileDialog::new().pick_files() {
            for path in paths {
                push_unique_path(&mut self.roster_form.file_paths, path.display().to_string());
            }
        }
    }

    fn choose_submission_folder(&mut self) {
        if let Some(path) = FileDialog::new().pick_folder() {
            self.submission_form.root_path = path.display().to_string();
        }
    }

    fn choose_review_materials(&mut self) {
        if let Some(paths) = FileDialog::new().pick_files() {
            for path in paths {
                push_unique_path(
                    &mut self.review_prep_form.material_paths,
                    path.display().to_string(),
                );
            }
        }
    }

    fn toolbar(&mut self, ui: &mut Ui) {
        let task_text = if self.pending_tasks > 0 {
            format!("处理中 {}", self.pending_tasks)
        } else {
            "空闲".to_owned()
        };
        let course_name = self
            .selected_course()
            .map(|course| course.course_name.clone())
            .unwrap_or_else(|| "未选择课程".to_owned());
        let assignment_name = self
            .selected_assignment()
            .map(|assignment| format!("第 {} 次 · {}", assignment.seq_no, assignment.title))
            .unwrap_or_else(|| "未选择作业".to_owned());

        ui.horizontal_wrapped(|ui| {
            egui::Frame::new()
                .fill(surface_color())
                .stroke(Stroke::new(1.0, border_color()))
                .corner_radius(CornerRadius::same(18))
                .inner_margin(Margin::symmetric(12, 9))
                .shadow(chip_shadow())
                .show(ui, |ui| {
                    ui.label(
                        RichText::new("TA")
                            .size(16.0)
                            .strong()
                            .color(accent_color()),
                    );
                });
            ui.add_space(2.0);
            ui.vertical(|ui| {
                ui.label(
                    RichText::new("助教 Agent")
                        .size(24.0)
                        .strong()
                        .color(text_primary_color()),
                );
                ui.label(
                    RichText::new(format!(
                        "{} · {}",
                        self.active_page.title(),
                        self.active_page.subtitle()
                    ))
                    .color(subtle_text_color()),
                );
            });
            ui.add_space(10.0);
            if command_button(ui, "刷新").clicked() {
                self.spawn_refresh();
            }
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
            status_chip(ui, "课程", &course_name, accent_color());
            status_chip(ui, "作业", &assignment_name, muted_chip_color());
        });
        ui.add_space(4.0);
        ui.label(
            RichText::new(&self.status)
                .small()
                .color(subtle_text_color()),
        );
    }

    fn navigation_panel(&mut self, ui: &mut Ui) {
        egui::ScrollArea::vertical()
            .id_salt("sidebar-scroll")
            .auto_shrink([false, false])
            .show(ui, |ui| {
                ui.vertical(|ui| {
                    ui.label(
                        RichText::new("助教自动化")
                            .size(19.0)
                            .strong()
                            .color(text_primary_color()),
                    );
                    ui.label(
                        RichText::new("Multi-Agent Workspace")
                            .small()
                            .color(subtle_text_color()),
                    );
                    ui.add_space(16.0);
                    ui.label(RichText::new("工作区").small().color(subtle_text_color()));
                    ui.add_space(8.0);
                    for page in WorkspacePage::ALL {
                        if navigation_button(ui, page, self.active_page == page).clicked() {
                            self.active_page = page;
                        }
                        ui.add_space(5.0);
                    }
                    ui.add_space(16.0);
                    section_card(ui, "当前上下文", "", |ui| {
                        if let Some(course) = self.selected_course() {
                            ui.label(RichText::new(&course.course_name).strong());
                            ui.label(format!("{} · {}", course.course_code, course.term));
                            ui.label(format!("状态：{}", course.status));
                        } else {
                            ui.label("还没有选择课程。");
                        }
                        ui.separator();
                        ui.label(format!(
                            "学生 {} · 作业 {}",
                            self.enrollments.len(),
                            self.assignments.len()
                        ));
                        ui.label(format!(
                            "提交 {} · 评审结果 {}",
                            self.submissions.len(),
                            self.review_results.len()
                        ));
                    });
                });
            });
    }

    fn workspace_panel(&mut self, ui: &mut Ui) {
        egui::ScrollArea::vertical()
            .id_salt(format!("workspace-scroll-{}", self.active_page.nav_index()))
            .auto_shrink([false, false])
            .show(ui, |ui| {
                self.render_page_header(ui);
                ui.add_space(12.0);
                match self.active_page {
                    WorkspacePage::Overview => self.render_overview_page(ui),
                    WorkspacePage::Summary => self.render_summary_page(ui),
                    WorkspacePage::Courses => self.render_courses_page(ui),
                    WorkspacePage::Assignments => self.render_assignments_page(ui),
                    WorkspacePage::Naming => self.render_naming_page(ui),
                    WorkspacePage::ReviewPrep => self.render_review_prep_page(ui),
                    WorkspacePage::ReviewRun => self.render_review_run_page(ui),
                    WorkspacePage::Audit => self.render_audit_page(ui),
                    WorkspacePage::Settings => self.render_settings_page(ui),
                }
            });
    }

    fn render_page_header(&mut self, ui: &mut Ui) {
        section_card(
            ui,
            self.active_page.title(),
            self.active_page.subtitle(),
            |ui| {
                if self.active_page == WorkspacePage::Overview {
                    ui.horizontal_wrapped(|ui| {
                        metric_card(
                            ui,
                            "服务",
                            self.health
                                .as_ref()
                                .map(|item| item.app_name.as_str())
                                .unwrap_or("未连接"),
                            self.health
                                .as_ref()
                                .map(|item| {
                                    if item.llm_enabled {
                                        "LLM 已启用"
                                    } else {
                                        "LLM 未启用"
                                    }
                                })
                                .unwrap_or("等待连接"),
                        );
                        metric_card(ui, "课程", &self.courses.len().to_string(), "独立课程空间");
                        metric_card(
                            ui,
                            "学生",
                            &self.enrollments.len().to_string(),
                            "当前课程名单",
                        );
                        metric_card(
                            ui,
                            "作业",
                            &self.assignments.len().to_string(),
                            "当前课程作业",
                        );
                        metric_card(
                            ui,
                            "Agent",
                            &self.agent_runs.len().to_string(),
                            "可追溯调用",
                        );
                    });
                }
            },
        );
    }

    fn render_overview_page(&mut self, ui: &mut Ui) {
        section_card(
            ui,
            "流程看板",
            "从课程初始化到发布评审结果的整体进度。",
            |ui| {
                ui.horizontal_wrapped(|ui| {
                    lifecycle_card(
                        ui,
                        "1",
                        "课程名单",
                        self.roster_batch
                            .as_ref()
                            .map(|item| item.status.as_str())
                            .unwrap_or("未开始"),
                        "初始化 Agent 识别学生名单",
                    );
                    lifecycle_card(
                        ui,
                        "2",
                        "作业导入",
                        self.submission_batch
                            .as_ref()
                            .map(|item| item.status.as_str())
                            .unwrap_or("未开始"),
                        "导入 Agent 匹配学生作业",
                    );
                    lifecycle_card(
                        ui,
                        "3",
                        "命名规范",
                        self.naming_plan
                            .as_ref()
                            .map(|item| item.status.as_str())
                            .unwrap_or("未开始"),
                        "生成计划后审批执行",
                    );
                    lifecycle_card(
                        ui,
                        "4",
                        "评审基线",
                        self.review_prep
                            .as_ref()
                            .map(|item| item.status.as_str())
                            .unwrap_or("未开始"),
                        "题目、答案与评分规范",
                    );
                    lifecycle_card(
                        ui,
                        "5",
                        "正式评审",
                        self.review_run
                            .as_ref()
                            .map(|item| item.status.as_str())
                            .unwrap_or("未开始"),
                        "多 Agent 并行评分",
                    );
                });
            },
        );
        ui.add_space(12.0);
        section_card(
            ui,
            "最近对象",
            "当前课程与作业的关键对象。",
            |ui| {
                two_columns(ui, |left, right| {
                    let ui = left;
                    self.render_course_selector(ui);
                    if ui.button("加载课程上下文").clicked() {
                        self.spawn_load_course_context();
                    }
                    let ui = right;
                    self.render_assignment_selector(ui);
                    if ui.button("加载作业上下文").clicked() {
                        self.spawn_load_assignment_context();
                    }
                });
            },
        );
    }

    fn render_summary_page(&mut self, ui: &mut Ui) {
        section_card(
            ui,
            "课程成绩汇总",
            "汇总已完成评分的结果；已发布结果优先，未发布的最终评分也会先显示。",
            |ui| {
                ui.horizontal_wrapped(|ui| {
                    self.render_course_selector(ui);
                    if ui.button("刷新汇总").clicked() {
                        self.spawn_load_course_review_summary();
                    }
                });
                ui.add_space(8.0);
                if let Some(summary) = &self.course_review_summary {
                    if summary.assignments.is_empty() {
                        empty_state(
                            ui,
                            "还没有作业",
                            "完成正式评审后，这里会显示课程汇总表。",
                        );
                        return;
                    }
                    course_review_summary_table(ui, summary);
                } else {
                    empty_state(
                        ui,
                        "还没有汇总数据",
                        "先选择课程并加载上下文或点击刷新汇总。",
                    );
                }
            },
        );
    }

    fn render_courses_page(&mut self, ui: &mut Ui) {
        two_columns(ui, |left, right| {
            let ui = left;
            section_card(
                ui,
                "创建课程",
                "每门课程都有独立名单、作业和评审链路。",
                |ui| {
                    labeled_text(ui, "课程编号", &mut self.course_form.course_code, "CS101");
                    labeled_text(
                        ui,
                        "课程名称",
                        &mut self.course_form.course_name,
                        "程序设计基础",
                    );
                    labeled_text(ui, "学期", &mut self.course_form.term, "2026 春季");
                    labeled_text(
                        ui,
                        "班级标签",
                        &mut self.course_form.class_label,
                        "1 班 / A 班",
                    );
                    labeled_text(ui, "授课教师", &mut self.course_form.teacher_name, "可选");
                    if ui.button("创建课程").clicked() {
                        self.spawn_create_course();
                    }
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "课程列表",
                "选择后加载对应的学生与作业。",
                |ui| {
                    self.render_course_selector(ui);
                    if ui.button("加载选中课程").clicked() {
                        self.spawn_load_course_context();
                    }
                    egui::ScrollArea::vertical()
                        .max_height(360.0)
                        .id_salt("courses-list-scroll")
                        .show(ui, |ui| {
                            for course in self.courses.clone() {
                                let selected =
                                    Some(&course.public_id) == self.selected_course_id.as_ref();
                                if selectable_card(
                                    ui,
                                    selected,
                                    &course.course_name,
                                    &format!(
                                        "{} · {} · {}",
                                        course.course_code, course.term, course.status
                                    ),
                                )
                                .clicked()
                                {
                                    self.selected_course_id = Some(course.public_id);
                                    self.course_context_requested_for = None;
                                    self.spawn_load_course_context();
                                }
                            }
                        });
                },
            );
            let ui = right;
            section_card(
                ui,
                "名单初始化",
                "上传 Excel、PDF、图片等材料，由初始化 Agent 输出候选学生。",
                |ui| {
                    let roster_running = self
                        .roster_batch
                        .as_ref()
                        .is_some_and(|batch| is_roster_runtime_active(&batch.status));
                    combo_box(
                        ui,
                        "roster-parse-mode",
                        "识别模式",
                        &mut self.roster_form.parse_mode,
                        &ROSTER_PARSE_MODES,
                    );
                    ui.horizontal(|ui| {
                        if ui.button("选择名单文件").clicked() {
                            self.choose_roster_files();
                        }
                        if ui.button("清空文件").clicked() {
                            self.roster_form.file_paths.clear();
                        }
                    });
                    path_list(ui, "roster-files", &self.roster_form.file_paths);
                    ui.horizontal_wrapped(|ui| {
                        if ui.button("1. 创建批次").clicked() {
                            self.spawn_create_roster_import();
                        }
                        if ui
                            .add_enabled(!roster_running, egui::Button::new("2. 运行 Agent"))
                            .clicked()
                        {
                            self.spawn_run_roster_import();
                        }
                        if ui
                            .add_enabled(roster_running, egui::Button::new("停止 Agent"))
                            .clicked()
                        {
                            self.spawn_cancel_roster_import();
                        }
                        if ui
                            .add_enabled(!roster_running, egui::Button::new("3. 批量接受候选"))
                            .clicked()
                        {
                            self.spawn_confirm_roster_import();
                        }
                        if ui
                            .add_enabled(!roster_running, egui::Button::new("4. 写入课程名单"))
                            .clicked()
                        {
                            self.spawn_apply_roster_import();
                        }
                    });
                    if roster_running {
                        ui.label(
                            RichText::new("停止为协作式取消，当前模型请求返回后会在下一节点停下。")
                                .small()
                                .color(subtle_text_color()),
                        );
                    }
                    if let Some(batch) = &self.roster_batch {
                        detail_line(ui, "批次", &batch.public_id);
                        detail_line(ui, "状态", &batch.status);
                        execution_state_line(ui, &batch.status);
                        if let Some(error) = &batch.error_message {
                            ui.colored_label(danger_color(), error);
                        }
                    }
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "学生名单",
                "候选学生确认后会成为课程名单。",
                |ui| {
                    ui.label(format!(
                        "候选 {} · 已入课 {}",
                        self.roster_candidates.len(),
                        self.enrollments.len()
                    ));
                    egui::ScrollArea::vertical()
                        .id_salt("roster-list-scroll")
                        .max_height(420.0)
                        .show(ui, |ui| {
                            if !self.roster_candidates.is_empty() {
                                candidate_table(ui, &self.roster_candidates);
                            } else {
                                enrollment_table(ui, &self.enrollments);
                            }
                        });
                },
            );
        });
    }

    fn render_assignments_page(&mut self, ui: &mut Ui) {
        two_columns(ui, |left, right| {
            let ui = left;
            section_card(
                ui,
                "创建作业",
                "作业是导入、命名和评审的独立单元。",
                |ui| {
                    self.render_course_selector(ui);
                    labeled_text(ui, "作业序号", &mut self.assignment_form.seq_no, "1");
                    labeled_text(ui, "标题", &mut self.assignment_form.title, "第一次作业");
                    labeled_multiline(ui, "说明", &mut self.assignment_form.description, "可选");
                    labeled_text(
                        ui,
                        "截止时间",
                        &mut self.assignment_form.due_at,
                        "可选，ISO 时间",
                    );
                    if ui.button("创建作业").clicked() {
                        self.spawn_create_assignment();
                    }
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "作业列表",
                "选择当前要处理的单次作业。",
                |ui| {
                    self.render_assignment_selector(ui);
                    if ui.button("加载作业上下文").clicked() {
                        self.spawn_load_assignment_context();
                    }
                    egui::ScrollArea::vertical()
                        .id_salt("assignments-list-scroll")
                        .max_height(360.0)
                        .show(ui, |ui| {
                            for assignment in self.assignments.clone() {
                                let selected = Some(&assignment.public_id)
                                    == self.selected_assignment_id.as_ref();
                                if selectable_card(
                                    ui,
                                    selected,
                                    &format!("第 {} 次 · {}", assignment.seq_no, assignment.title),
                                    &assignment.status,
                                )
                                .clicked()
                                {
                                    self.selected_assignment_id = Some(assignment.public_id);
                                    self.spawn_load_assignment_context();
                                }
                            }
                        });
                },
            );
            let ui = right;
            section_card(
                ui,
                "作业导入",
                "选择文件夹后由导入 Agent 匹配作业与学生。",
                |ui| {
                    let submission_running = self
                        .submission_batch
                        .as_ref()
                        .is_some_and(|batch| is_submission_runtime_active(&batch.status));
                    ui.horizontal(|ui| {
                        ui.add(
                            TextEdit::singleline(&mut self.submission_form.root_path)
                                .id_salt("submission-root-path")
                                .desired_width(360.0)
                                .hint_text("作业文件夹路径"),
                        );
                        if ui.button("选择文件夹").clicked() {
                            self.choose_submission_folder();
                        }
                    });
                    ui.horizontal_wrapped(|ui| {
                        if ui.button("1. 创建批次").clicked() {
                            self.spawn_create_submission_import();
                        }
                        if ui
                            .add_enabled(
                                !submission_running,
                                egui::Button::new("2. 运行导入 Agent"),
                            )
                            .clicked()
                        {
                            self.spawn_run_submission_import();
                        }
                        if ui
                            .add_enabled(submission_running, egui::Button::new("停止 Agent"))
                            .clicked()
                        {
                            self.spawn_cancel_submission_import();
                        }
                        if ui
                            .add_enabled(!submission_running, egui::Button::new("3. 批量确认匹配"))
                            .clicked()
                        {
                            self.spawn_confirm_submission_import();
                        }
                        if ui
                            .add_enabled(!submission_running, egui::Button::new("4. 应用导入"))
                            .clicked()
                        {
                            self.spawn_apply_submission_import();
                        }
                    });
                    if submission_running {
                        ui.label(
                            RichText::new("后台会自动轮询导入状态，停止同样是协作式取消。")
                                .small()
                                .color(subtle_text_color()),
                        );
                    }
                    if let Some(batch) = &self.submission_batch {
                        detail_line(ui, "批次", &batch.public_id);
                        detail_line(ui, "状态", &batch.status);
                        execution_state_line(ui, &batch.status);
                        detail_line(ui, "根目录", &batch.root_path);
                    }
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "提交记录",
                "展示 Agent 匹配结果、置信度和当前路径。",
                |ui| {
                    submission_table(ui, &self.submissions);
                },
            );
        });
    }

    fn render_naming_page(&mut self, ui: &mut Ui) {
        two_columns(ui, |left, right| {
            let ui = left;
            section_card(
                ui,
                "命名策略",
                "可以写模板，也可以写自然语言规范交给命名 Agent 归一化。",
                |ui| {
                    self.render_assignment_selector(ui);
                    labeled_text(
                        ui,
                        "模板",
                        &mut self.naming_form.template_text,
                        "{assignment}_{student_no}_{name}",
                    );
                    labeled_multiline(
                        ui,
                        "文字规范",
                        &mut self.naming_form.natural_language_rule,
                        "说明命名规则",
                    );
                    if ui.button("创建/更新策略").clicked() {
                        self.spawn_create_naming_policy();
                    }
                    policy_selector(ui, &self.naming_policies, &mut self.selected_policy_id);
                    if ui.button("生成命名计划").clicked() {
                        self.spawn_create_naming_plan();
                    }
                },
            );
            ui.add_space(12.0);
            self.render_approval_card(ui, true);
            let ui = right;
            section_card(
                ui,
                "命名计划",
                "整批命名操作统一审批，审批前只展示计划和命令预览，不会修改文件。",
                |ui| {
                    if let Some(plan) = &self.naming_plan {
                        detail_line(ui, "计划", &plan.public_id);
                        detail_line(ui, "状态", &plan.status);
                        ui.horizontal_wrapped(|ui| {
                            if ui.button("提交审批").clicked() {
                                self.spawn_submit_naming_approval();
                            }
                            if ui.button("审批后执行改名").clicked() {
                                self.spawn_execute_naming_plan();
                            }
                            if ui.button("回滚改名").clicked() {
                                self.spawn_rollback_naming_plan();
                            }
                        });
                        naming_operation_table(ui, &plan.operations);
                    } else {
                        empty_state(ui, "还没有命名计划", "先选择作业并生成命名计划。");
                    }
                },
            );
        });
    }

    fn render_review_prep_page(&mut self, ui: &mut Ui) {
        two_columns(ui, |left, right| {
            let ui = left;
            section_card(
                ui,
                "评审初始化",
                "上传题目、答案、评分规范等材料，评审初始化 Agent 生成结构化基线。",
                |ui| {
                    let review_prep_running = self
                        .review_prep
                        .as_ref()
                        .is_some_and(|prep| is_review_prep_runtime_active(&prep.status));
                    self.render_assignment_selector(ui);
                    ui.horizontal(|ui| {
                        if ui.button("选择材料文件").clicked() {
                            self.choose_review_materials();
                        }
                        if ui.button("清空材料").clicked() {
                            self.review_prep_form.material_paths.clear();
                        }
                    });
                    path_list(
                        ui,
                        "review-materials",
                        &self.review_prep_form.material_paths,
                    );
                    ui.horizontal_wrapped(|ui| {
                        if ui.button("1. 创建初始化版本").clicked() {
                            self.spawn_create_review_prep();
                        }
                        if ui
                            .add_enabled(
                                !review_prep_running,
                                egui::Button::new("2. 运行初始化 Agent"),
                            )
                            .clicked()
                        {
                            self.spawn_run_review_prep();
                        }
                        if ui
                            .add_enabled(review_prep_running, egui::Button::new("停止 Agent"))
                            .clicked()
                        {
                            self.spawn_cancel_review_prep();
                        }
                        if ui
                            .add_enabled(!review_prep_running, egui::Button::new("3. 确认基线"))
                            .clicked()
                        {
                            self.spawn_confirm_review_prep();
                        }
                    });
                    if review_prep_running {
                        ui.label(
                            RichText::new("评审初始化运行中，题目项和答案会自动刷新。")
                                .small()
                                .color(subtle_text_color()),
                        );
                    }
                    if let Some(prep) = &self.review_prep {
                        detail_line(
                            ui,
                            "版本",
                            &format!("v{} · {}", prep.version_no, prep.status),
                        );
                        detail_line(ui, "ID", &prep.public_id);
                        execution_state_line(ui, &prep.status);
                    }
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "题目项",
                "单题单题检查题目、答案和评分规范。",
                |ui| {
                    egui::ScrollArea::vertical()
                        .id_salt("review-questions-scroll")
                        .max_height(440.0)
                        .show(ui, |ui| {
                            for item in self.review_questions.clone() {
                                let selected =
                                    Some(&item.public_id) == self.selected_question_id.as_ref();
                                if selectable_card(
                                    ui,
                                    selected,
                                    &format!("题 {} · {} 分", item.question_no, item.score_weight),
                                    &shorten(&item.question_full_text, 82),
                                )
                                .clicked()
                                {
                                    self.selected_question_id = Some(item.public_id);
                                    self.sync_question_form();
                                }
                            }
                        });
                },
            );
            let ui = right;
            section_card(
                ui,
                "题目编辑",
                "确认前可以人工修正 Agent 生成的结构化内容。",
                |ui| {
                    labeled_multiline(
                        ui,
                        "完整题目",
                        &mut self.review_prep_form.question_text,
                        "题目全文",
                    );
                    labeled_multiline(
                        ui,
                        "简洁答案",
                        &mut self.review_prep_form.answer_short,
                        "答案摘要",
                    );
                    labeled_multiline(
                        ui,
                        "完整答案",
                        &mut self.review_prep_form.answer_full,
                        "完整答案",
                    );
                    labeled_multiline(
                        ui,
                        "评分规范",
                        &mut self.review_prep_form.rubric,
                        "评分细则",
                    );
                    labeled_text(
                        ui,
                        "分值权重",
                        &mut self.review_prep_form.score_weight,
                        "100",
                    );
                    labeled_text(
                        ui,
                        "状态",
                        &mut self.review_prep_form.status,
                        "draft / ready",
                    );
                    if ui.button("保存题目项").clicked() {
                        self.spawn_patch_review_question();
                    }
                },
            );
        });
    }

    fn render_review_run_page(&mut self, ui: &mut Ui) {
        two_columns(ui, |left, right| {
            let ui = left;
            section_card(
                ui,
                "正式评审",
                "创建运行后，多 Agent 会按提交并行评分。",
                |ui| {
                    let review_run_running = self
                        .review_run
                        .as_ref()
                        .is_some_and(|run| is_review_run_runtime_active(&run.status));
                    self.render_assignment_selector(ui);
                    labeled_text(
                        ui,
                        "并行数",
                        &mut self.review_run_form.parallelism,
                        "留空则使用设置页默认值",
                    );
                    if let Some(health) = &self.health {
                        detail_line(
                            ui,
                            "默认并行",
                            &health
                                .review_runtime_settings
                                .review_run_default_parallelism
                                .to_string(),
                        );
                        detail_line(
                            ui,
                            "校验 Agent",
                            if health
                                .review_runtime_settings
                                .review_run_enable_validation_agent
                            {
                                "开启"
                            } else {
                                "关闭"
                            },
                        );
                    }
                    ui.horizontal_wrapped(|ui| {
                        if ui.button("1. 创建评审运行").clicked() {
                            self.spawn_create_review_run();
                        }
                        if ui
                            .add_enabled(
                                !review_run_running,
                                egui::Button::new("2. 启动评审 Agent"),
                            )
                            .clicked()
                        {
                            self.spawn_start_review_run();
                        }
                        if ui
                            .add_enabled(review_run_running, egui::Button::new("停止 Agent"))
                            .clicked()
                        {
                            self.spawn_cancel_review_run();
                        }
                        if ui.button("刷新结果").clicked() {
                            self.spawn_refresh_review_results();
                        }
                        if ui
                            .add_enabled(!review_run_running, egui::Button::new("重试失败项"))
                            .clicked()
                        {
                            self.spawn_retry_review_run();
                        }
                        if ui
                            .add_enabled(!review_run_running, egui::Button::new("提交发布审批"))
                            .clicked()
                        {
                            self.spawn_publish_review_run();
                        }
                    });
                    if review_run_running {
                        ui.label(
                            RichText::new("正式评审正在后台执行，结果列表会自动刷新。")
                                .small()
                                .color(subtle_text_color()),
                        );
                    }
                    if let Some(run) = &self.review_run {
                        detail_line(ui, "运行", &run.public_id);
                        detail_line(ui, "状态", &run.status);
                        execution_state_line(ui, &run.status);
                        detail_line(ui, "并行", &run.parallelism.to_string());
                    }
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "评审结果",
                "每条结果都直接显示学生、文件、分数和状态。",
                |ui| {
                    if review_result_table(ui, &self.review_results, &mut self.selected_result_id) {
                        self.sync_result_form();
                    }
                },
            );
            let ui = right;
            section_card(
                ui,
                "结果详情与复核",
                "人工复核会覆盖该结果的最终分数与说明。",
                |ui| {
                    if let Some(result) = self.selected_result() {
                        detail_line(ui, "结果", &result.public_id);
                        detail_line(
                            ui,
                            "学生",
                            &format!(
                                "{} {}",
                                result.student_no.as_deref().unwrap_or("-"),
                                result.student_name.as_deref().unwrap_or("未匹配学生")
                            ),
                        );
                        detail_line(ui, "提交", &result.submission_public_id);
                        detail_line(ui, "文件", &result.source_entry_name);
                        detail_line(ui, "路径", &result.current_path);
                        detail_line(ui, "状态", &result.status);
                        ui.label(
                            RichText::new("Agent 说明")
                                .small()
                                .color(subtle_text_color()),
                        );
                        ui.label(result.summary.as_deref().unwrap_or("暂无说明"));
                        if let Some(value) = &result.result {
                            json_block(ui, value);
                        }
                    } else {
                        empty_state(ui, "还没有选中结果", "启动评审后选择结果进行复核。");
                    }
                    ui.separator();
                    labeled_text(
                        ui,
                        "人工分数",
                        &mut self.review_run_form.manual_score,
                        "0-100",
                    );
                    labeled_multiline(
                        ui,
                        "人工说明",
                        &mut self.review_run_form.manual_summary,
                        "复核理由",
                    );
                    labeled_text(
                        ui,
                        "人工决策",
                        &mut self.review_run_form.manual_decision,
                        "manual_reviewed",
                    );
                    if ui.button("保存人工复核").clicked() {
                        self.spawn_manual_review_result();
                    }
                },
            );
            ui.add_space(12.0);
            self.render_approval_card(ui, false);
        });
    }

    fn render_audit_page(&mut self, ui: &mut Ui) {
        two_columns(ui, |left, right| {
            let ui = left;
            section_card(
                ui,
                "Agent 调用",
                "记录 Agent 输入输出引用、模型、状态和错误。",
                |ui| {
                    if ui.button("刷新审计日志").clicked() {
                        self.spawn_load_audit();
                    }
                    egui::ScrollArea::vertical()
                        .id_salt("agent-runs-scroll")
                        .max_height(420.0)
                        .show(ui, |ui| {
                            for run in self.agent_runs.clone() {
                                let selected =
                                    Some(&run.public_id) == self.selected_agent_run_id.as_ref();
                                if selectable_card(
                                    ui,
                                    selected,
                                    &format!("{} · {}", run.agent_name, run.status),
                                    &format!("{} / {}", run.graph_name, run.stage_name),
                                )
                                .clicked()
                                {
                                    self.selected_agent_run_id = Some(run.public_id);
                                    self.tool_calls.clear();
                                }
                            }
                        });
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "课程审计",
                "记录课程维度的上传、确认、执行等事件。",
                |ui| {
                    audit_table(ui, &self.audit_events);
                },
            );
            let ui = right;
            section_card(
                ui,
                "调用详情",
                "工具调用和结构化输出引用集中查看。",
                |ui| {
                    if let Some(run) = self.selected_agent_run() {
                        detail_line(ui, "Agent", &run.agent_name);
                        detail_line(ui, "图", &run.graph_name);
                        detail_line(ui, "阶段", &run.stage_name);
                        detail_line(ui, "状态", &run.status);
                        if let Some(error) = &run.error_message {
                            ui.colored_label(danger_color(), error);
                        }
                        if ui.button("加载工具调用").clicked() {
                            self.spawn_load_tool_calls();
                        }
                        ui.separator();
                        egui::ScrollArea::vertical()
                            .id_salt("tool-calls-scroll")
                            .max_height(420.0)
                            .show(ui, |ui| {
                                for call in &self.tool_calls {
                                    inner_panel_frame().show(ui, |ui| {
                                        ui.label(RichText::new(&call.tool_name).strong());
                                        ui.label(format!(
                                            "状态：{} · 退出码：{}",
                                            call.status,
                                            call.exit_code
                                                .map(|value| value.to_string())
                                                .unwrap_or_else(|| "-".to_owned())
                                        ));
                                        if let Some(command) = &call.command_text {
                                            ui.monospace(command);
                                        }
                                    });
                                    ui.add_space(6.0);
                                }
                            });
                    } else {
                        empty_state(ui, "没有 Agent 调用", "点击刷新审计日志。");
                    }
                },
            );
        });
    }

    fn render_settings_page(&mut self, ui: &mut Ui) {
        two_columns(ui, |left, right| {
            let ui = left;
            section_card(
                ui,
                "连接与状态",
                "桌面端连接目标、运行目录和模型可用性。",
                |ui| {
                    labeled_text(
                        ui,
                        "后端地址",
                        &mut self.backend_url,
                        "http://127.0.0.1:18080",
                    );
                    if ui.button("检测连接").clicked() {
                        self.spawn_task("检测连接", |api| {
                            Ok(vec![WorkerEvent::SnapshotLoaded(DashboardSnapshot {
                                health: Some(api.health()?),
                                courses: api.list_courses().unwrap_or_default(),
                            })])
                        });
                    }
                    if let Some(health) = &self.health {
                        detail_line(ui, "应用", &health.app_name);
                        detail_line(ui, "数据库", &health.database_url);
                        detail_line(ui, "运行目录", &health.runtime_root);
                        detail_line(
                            ui,
                            "LLM",
                            if health.llm_enabled {
                                "已启用"
                            } else {
                                "未启用"
                            },
                        );
                    }
                    ui.horizontal_wrapped(|ui| {
                        if ui.button("刷新运行设置").clicked() {
                            self.spawn_load_review_settings();
                        }
                        if ui.button("保存全部设置").clicked() {
                            self.spawn_save_review_settings();
                        }
                    });
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "1. 名单与作业导入",
                "控制压缩包递归展开与单次导入可处理的文件量。",
                |ui| {
                    labeled_text(
                        ui,
                        "压缩包递归深度",
                        &mut self.review_settings_form.submission_unpack_max_depth,
                        "1-10",
                    );
                    labeled_text(
                        ui,
                        "压缩包最大文件数",
                        &mut self.review_settings_form.submission_unpack_max_files,
                        "1-2000",
                    );
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "4. 评审初始化",
                "控制题目解析后答案生成与纠正的最多轮数。",
                |ui| {
                    labeled_text(
                        ui,
                        "答案生成最大轮数",
                        &mut self.review_settings_form.review_prep_max_answer_rounds,
                        "1-8",
                    );
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "5. 正式评审",
                "控制并行评分、校验轮次、分值量程和文档内嵌图片数量。",
                |ui| {
                    labeled_text(
                        ui,
                        "默认并行数",
                        &mut self.review_settings_form.review_run_default_parallelism,
                        "1-32",
                    );
                    labeled_text(
                        ui,
                        "默认总分",
                        &mut self.review_settings_form.default_review_scale,
                        "通常为 100",
                    );
                    labeled_text(
                        ui,
                        "每份作业图片上限",
                        &mut self.review_settings_form.vision_max_assets_per_submission,
                        "1-32",
                    );
                    ui.checkbox(
                        &mut self.review_settings_form.review_run_enable_validation_agent,
                        "正式评审启用二次校验 Agent",
                    );
                },
            );
            let ui = right;
            section_card(
                ui,
                "模型请求",
                "控制每次 LLM 请求等待时间和失败重试次数。",
                |ui| {
                    labeled_text(
                        ui,
                        "请求超时秒数",
                        &mut self.review_settings_form.llm_timeout_seconds,
                        "10-900",
                    );
                    labeled_text(
                        ui,
                        "请求重试次数",
                        &mut self.review_settings_form.llm_max_retries,
                        "0-8",
                    );
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "本地后端",
                "桌面端可以托管后端进程，也可以连接外部后端。",
                |ui| {
                    labeled_text(
                        ui,
                        "后端目录",
                        &mut self.backend_control.backend_dir,
                        "backend 目录",
                    );
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
                    detail_line(ui, "状态", &self.backend_control.state);
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "当前生效",
                "后端返回的运行设置快照。",
                |ui| {
                    if let Some(health) = &self.health {
                        detail_line(
                            ui,
                            "答案轮数",
                            &health
                                .review_runtime_settings
                                .review_prep_max_answer_rounds
                                .to_string(),
                        );
                        detail_line(
                            ui,
                            "默认并行",
                            &health
                                .review_runtime_settings
                                .review_run_default_parallelism
                                .to_string(),
                        );
                        detail_line(
                            ui,
                            "默认总分",
                            &health
                                .review_runtime_settings
                                .default_review_scale
                                .to_string(),
                        );
                        detail_line(
                            ui,
                            "解压深度",
                            &health
                                .review_runtime_settings
                                .submission_unpack_max_depth
                                .to_string(),
                        );
                        detail_line(
                            ui,
                            "文件上限",
                            &health
                                .review_runtime_settings
                                .submission_unpack_max_files
                                .to_string(),
                        );
                        detail_line(
                            ui,
                            "图片上限",
                            &health
                                .review_runtime_settings
                                .vision_max_assets_per_submission
                                .to_string(),
                        );
                        detail_line(
                            ui,
                            "请求超时",
                            &format!(
                                "{} 秒",
                                format_compact_f64(
                                    health.review_runtime_settings.llm_timeout_seconds
                                )
                            ),
                        );
                        detail_line(
                            ui,
                            "请求重试",
                            &health.review_runtime_settings.llm_max_retries.to_string(),
                        );
                        detail_line(
                            ui,
                            "校验 Agent",
                            if health
                                .review_runtime_settings
                                .review_run_enable_validation_agent
                            {
                                "开启"
                            } else {
                                "关闭"
                            },
                        );
                    } else {
                        empty_state(ui, "未连接后端", "检测连接后会显示当前运行设置。");
                    }
                },
            );
            ui.add_space(12.0);
            section_card(
                ui,
                "后端日志",
                "只显示桌面端托管进程的 stdout/stderr。",
                |ui| {
                    egui::ScrollArea::vertical()
                        .id_salt("backend-logs-scroll")
                        .max_height(360.0)
                        .stick_to_bottom(true)
                        .show(ui, |ui| {
                            for line in &self.backend_control.logs {
                                ui.monospace(line);
                            }
                        });
                },
            );
        });
    }

    fn render_course_selector(&mut self, ui: &mut Ui) {
        let previous_course_id = self.selected_course_id.clone();
        ui.label(RichText::new("课程").small().color(subtle_text_color()));
        egui::ComboBox::from_id_salt("course-selector")
            .width(ui.available_width().max(320.0))
            .selected_text(
                self.selected_course()
                    .map(|course| course.course_name.clone())
                    .unwrap_or_else(|| "请选择课程".to_owned()),
            )
            .show_ui(ui, |ui| {
                for course in &self.courses {
                    ui.selectable_value(
                        &mut self.selected_course_id,
                        Some(course.public_id.clone()),
                        format!("{} · {}", course.course_code, course.course_name),
                    );
                }
            });
        if previous_course_id != self.selected_course_id {
            self.course_context_requested_for = None;
        }
    }

    fn render_assignment_selector(&mut self, ui: &mut Ui) {
        ui.label(RichText::new("作业").small().color(subtle_text_color()));
        egui::ComboBox::from_id_salt("assignment-selector")
            .width(ui.available_width().max(320.0))
            .selected_text(
                self.selected_assignment()
                    .map(|item| format!("第 {} 次 · {}", item.seq_no, item.title))
                    .unwrap_or_else(|| "请选择作业".to_owned()),
            )
            .show_ui(ui, |ui| {
                for assignment in &self.assignments {
                    ui.selectable_value(
                        &mut self.selected_assignment_id,
                        Some(assignment.public_id.clone()),
                        format!("第 {} 次 · {}", assignment.seq_no, assignment.title),
                    );
                }
            });
    }

    fn render_approval_card(&mut self, ui: &mut Ui, naming_mode: bool) {
        section_card(
            ui,
            "审批控制",
            if naming_mode {
                "以下命名操作会作为一个审批任务统一批准或拒绝。"
            } else {
                "高风险副作用必须先审批，再执行。"
            },
            |ui| {
                if let Some(task) = &self.active_approval {
                    let approval_pending = task.status == "pending";
                    let approval_approved = task.status == "approved";
                    let action_locked = self.pending_tasks > 0;
                    detail_line(ui, "审批", &task.public_id);
                    detail_line(ui, "标题", &task.title);
                    detail_line(
                        ui,
                        "动作",
                        &format!("{} / {}", task.object_type, task.action_type),
                    );
                    detail_line(ui, "状态", &task.status);
                    if let Some(summary) = &task.summary {
                        ui.label(summary);
                    }
                    labeled_multiline(
                        ui,
                        "审批备注",
                        if naming_mode {
                            &mut self.naming_form.approval_note
                        } else {
                            &mut self.review_run_form.publish_note
                        },
                        "说明批准或拒绝原因",
                    );
                    ui.horizontal_wrapped(|ui| {
                        if ui
                            .add_enabled(
                                !action_locked && approval_pending,
                                egui::Button::new("批准"),
                            )
                            .clicked()
                        {
                            self.spawn_approve_active_task();
                        }
                        if ui
                            .add_enabled(
                                !action_locked && approval_pending,
                                egui::Button::new("拒绝"),
                            )
                            .clicked()
                        {
                            self.spawn_reject_active_task();
                        }
                        if !naming_mode
                            && ui
                                .add_enabled(
                                    !action_locked && approval_approved,
                                    egui::Button::new("执行发布副作用"),
                                )
                                .clicked()
                        {
                            self.spawn_execute_active_approval();
                        }
                    });
                    egui::ScrollArea::vertical()
                        .id_salt("approval-command-preview-scroll")
                        .max_height(220.0)
                        .show(ui, |ui| {
                            for command in &task.command_preview {
                                json_block(ui, command);
                            }
                        });
                } else {
                    empty_state(ui, "暂无审批任务", "命名计划或发布结果提交后会显示在这里。");
                }
            },
        );
    }
}

impl eframe::App for AssistantApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.poll_backend_process();
        self.drain_events();
        if self.has_active_runtime_job() {
            if !self.runtime_poll_in_flight
                && self.last_runtime_poll_at.elapsed() >= RUNTIME_POLL_INTERVAL
            {
                self.spawn_runtime_poll();
            }
            ctx.request_repaint_after(Duration::from_millis(250));
        }

        egui::TopBottomPanel::top("toolbar")
            .frame(
                egui::Frame::new()
                    .fill(toolbar_color())
                    .inner_margin(Margin::symmetric(20, 14))
                    .stroke(Stroke::new(1.0, border_color())),
            )
            .show(ctx, |ui| self.toolbar(ui));

        egui::SidePanel::left("sidebar")
            .resizable(true)
            .default_width(238.0)
            .width_range(176.0..=320.0)
            .frame(
                egui::Frame::new()
                    .fill(sidebar_color())
                    .inner_margin(Margin::same(16))
                    .stroke(Stroke::new(1.0, border_color())),
            )
            .show(ctx, |ui| self.navigation_panel(ui));

        egui::CentralPanel::default()
            .frame(
                egui::Frame::new()
                    .fill(canvas_color())
                    .inner_margin(Margin::same(18)),
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
    style.spacing.button_padding = egui::vec2(16.0, 10.0);
    style.spacing.interact_size = egui::vec2(42.0, 40.0);
    style.spacing.text_edit_width = 340.0;
    style.spacing.combo_width = 340.0;
    style.visuals = egui::Visuals::light();
    style.visuals.override_text_color = Some(text_primary_color());
    style.visuals.panel_fill = canvas_color();
    style.visuals.window_fill = surface_color();
    style.visuals.extreme_bg_color = surface_alt_color();
    style.visuals.faint_bg_color = soft_tint(border_color());
    style.visuals.window_corner_radius = CornerRadius::same(22);
    style.visuals.window_stroke = Stroke::new(1.0, border_color());
    style.visuals.window_shadow = card_shadow();
    style.visuals.popup_shadow = chip_shadow();
    style.visuals.widgets.noninteractive.bg_fill = surface_color();
    style.visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0, border_color());
    style.visuals.widgets.noninteractive.corner_radius = CornerRadius::same(16);
    style.visuals.widgets.inactive.bg_fill = surface_color();
    style.visuals.widgets.inactive.weak_bg_fill = surface_alt_color();
    style.visuals.widgets.inactive.bg_stroke = Stroke::new(1.0, border_color());
    style.visuals.widgets.inactive.corner_radius = CornerRadius::same(14);
    style.visuals.widgets.hovered.bg_fill = surface_alt_color();
    style.visuals.widgets.hovered.weak_bg_fill = soft_tint(accent_color());
    style.visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, accent_soft_color());
    style.visuals.widgets.hovered.corner_radius = CornerRadius::same(14);
    style.visuals.widgets.active.bg_fill = soft_tint(accent_color());
    style.visuals.widgets.active.bg_stroke = Stroke::new(1.0, accent_color());
    style.visuals.widgets.active.corner_radius = CornerRadius::same(14);
    style.visuals.widgets.open = style.visuals.widgets.hovered;
    style.visuals.selection.bg_fill = accent_color();
    style.visuals.selection.stroke = Stroke::new(1.0, Color32::WHITE);
    style.text_styles.insert(
        egui::TextStyle::Heading,
        FontId::new(28.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Body,
        FontId::new(16.5, FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Button,
        FontId::new(15.5, FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Small,
        FontId::new(14.0, FontFamily::Proportional),
    );
    ctx.set_style(style);
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

fn section_card<R>(
    ui: &mut Ui,
    title: &str,
    subtitle: &str,
    add_contents: impl FnOnce(&mut Ui) -> R,
) -> R {
    egui::Frame::new()
        .fill(surface_color())
        .stroke(Stroke::new(1.0, border_color()))
        .corner_radius(CornerRadius::same(22))
        .inner_margin(Margin::same(16))
        .outer_margin(Margin::symmetric(0, 3))
        .shadow(card_shadow())
        .show(ui, |ui| {
            if !title.is_empty() {
                ui.label(
                    RichText::new(title)
                        .size(19.0)
                        .strong()
                        .color(text_primary_color()),
                );
            }
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
        .stroke(Stroke::new(1.0, soft_border_color()))
        .corner_radius(CornerRadius::same(18))
        .inner_margin(Margin::same(12))
        .shadow(chip_shadow())
}

fn two_columns(ui: &mut Ui, contents: impl FnOnce(&mut Ui, &mut Ui)) {
    let available_width = ui.available_width();
    ui.columns(2, |columns| {
        let (left_slice, right_slice) = columns.split_at_mut(1);
        if available_width >= 1380.0 {
            left_slice[0].set_width(available_width * 0.52);
            right_slice[0].set_width(available_width * 0.46);
        }
        contents(&mut left_slice[0], &mut right_slice[0]);
    });
}

fn navigation_button(ui: &mut Ui, page: WorkspacePage, selected: bool) -> egui::Response {
    let fill = if selected {
        surface_color()
    } else {
        Color32::TRANSPARENT
    };
    let stroke_color = if selected {
        border_color()
    } else {
        Color32::TRANSPARENT
    };
    let text_color = if selected {
        text_primary_color()
    } else {
        subtle_text_color()
    };
    ui.add_sized(
        [ui.available_width(), 42.0],
        egui::Button::new(
            RichText::new(format!("{}  {}", page.nav_index(), page.title()))
                .color(text_color)
                .strong(),
        )
        .fill(fill)
        .stroke(Stroke::new(1.0, stroke_color))
        .corner_radius(CornerRadius::same(15)),
    )
}

fn selectable_card(ui: &mut Ui, selected: bool, title: &str, subtitle: &str) -> egui::Response {
    let fill = if selected {
        selected_surface_color()
    } else {
        surface_alt_color()
    };
    let stroke = if selected {
        accent_soft_color()
    } else {
        soft_border_color()
    };
    let response = egui::Frame::new()
        .fill(fill)
        .stroke(Stroke::new(1.0, stroke))
        .corner_radius(CornerRadius::same(17))
        .inner_margin(Margin::same(12))
        .shadow(chip_shadow())
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.label(
                RichText::new(title)
                    .size(16.5)
                    .strong()
                    .color(text_primary_color()),
            );
            if !subtitle.is_empty() {
                ui.label(
                    RichText::new(subtitle)
                        .size(14.2)
                        .color(subtle_text_color()),
                );
            }
        })
        .response;
    ui.add_space(6.0);
    response.interact(egui::Sense::click())
}

fn status_chip(ui: &mut Ui, label: &str, value: &str, color: Color32) {
    egui::Frame::new()
        .fill(soft_tint(color))
        .stroke(Stroke::new(1.0, color.gamma_multiply(0.55)))
        .corner_radius(CornerRadius::same(18))
        .inner_margin(Margin::symmetric(10, 6))
        .show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label(RichText::new(label).small().color(subtle_text_color()));
                ui.label(RichText::new(value).strong().color(text_primary_color()));
            });
        });
}

fn command_button(ui: &mut Ui, label: &str) -> egui::Response {
    ui.add(
        egui::Button::new(RichText::new(label).strong().color(accent_color()))
            .fill(selected_surface_color())
            .stroke(Stroke::new(1.0, accent_soft_color()))
            .corner_radius(CornerRadius::same(16)),
    )
}

fn metric_card(ui: &mut Ui, title: &str, value: &str, help: &str) {
    egui::Frame::new()
        .fill(surface_alt_color())
        .stroke(Stroke::new(1.0, soft_border_color()))
        .corner_radius(CornerRadius::same(18))
        .inner_margin(Margin::same(14))
        .shadow(chip_shadow())
        .show(ui, |ui| {
            ui.set_min_width(132.0);
            ui.set_min_height(82.0);
            ui.label(RichText::new(title).small().color(subtle_text_color()));
            ui.label(
                RichText::new(value)
                    .size(23.0)
                    .strong()
                    .color(text_primary_color()),
            );
            ui.label(RichText::new(help).small().color(subtle_text_color()));
        });
}

fn lifecycle_card(ui: &mut Ui, index: &str, title: &str, status: &str, help: &str) {
    egui::Frame::new()
        .fill(surface_alt_color())
        .stroke(Stroke::new(1.0, soft_border_color()))
        .corner_radius(CornerRadius::same(19))
        .inner_margin(Margin::same(14))
        .shadow(chip_shadow())
        .show(ui, |ui| {
            ui.set_min_width(156.0);
            ui.horizontal(|ui| {
                egui::Frame::new()
                    .fill(soft_tint(status_color(status)))
                    .stroke(Stroke::new(1.0, status_color(status).gamma_multiply(0.55)))
                    .corner_radius(CornerRadius::same(14))
                    .inner_margin(Margin::symmetric(9, 6))
                    .show(ui, |ui| {
                        ui.label(RichText::new(index).strong().color(status_color(status)));
                    });
                ui.vertical(|ui| {
                    ui.label(RichText::new(title).strong().color(text_primary_color()));
                    ui.colored_label(status_color(status), status);
                });
            });
            ui.add_space(2.0);
            ui.label(RichText::new(help).small().color(subtle_text_color()));
        });
}

fn combo_box(ui: &mut Ui, id: &str, label: &str, current: &mut String, options: &[(&str, &str)]) {
    ui.label(RichText::new(label).small().color(subtle_text_color()));
    egui::ComboBox::from_id_salt(id)
        .selected_text(mode_label(current, options))
        .show_ui(ui, |ui| {
            for (value, title) in options {
                ui.selectable_value(current, (*value).to_owned(), *title);
            }
        });
}

fn policy_selector(
    ui: &mut Ui,
    policies: &[NamingPolicyRead],
    selected_policy_id: &mut Option<String>,
) {
    ui.label(RichText::new("已有策略").small().color(subtle_text_color()));
    egui::ComboBox::from_id_salt("policy-selector")
        .selected_text(
            policies
                .iter()
                .find(|policy| Some(&policy.public_id) == selected_policy_id.as_ref())
                .map(|policy| format!("v{} · {}", policy.version_no, policy.template_text))
                .unwrap_or_else(|| "不使用已有策略".to_owned()),
        )
        .show_ui(ui, |ui| {
            ui.selectable_value(selected_policy_id, None, "不使用已有策略");
            for policy in policies {
                ui.selectable_value(
                    selected_policy_id,
                    Some(policy.public_id.clone()),
                    format!("v{} · {}", policy.version_no, policy.template_text),
                );
            }
        });
}

fn labeled_text(ui: &mut Ui, label: &str, value: &mut String, hint: &str) {
    ui.label(RichText::new(label).small().color(subtle_text_color()));
    ui.add(
        TextEdit::singleline(value)
            .id_salt(label)
            .desired_width(f32::INFINITY)
            .hint_text(hint),
    );
}

fn labeled_multiline(ui: &mut Ui, label: &str, value: &mut String, hint: &str) {
    ui.label(RichText::new(label).small().color(subtle_text_color()));
    ui.add(
        TextEdit::multiline(value)
            .id_salt(label)
            .desired_width(f32::INFINITY)
            .desired_rows(4)
            .hint_text(hint),
    );
}

fn detail_line(ui: &mut Ui, label: &str, value: &str) {
    ui.horizontal_wrapped(|ui| {
        ui.label(RichText::new(label).small().color(subtle_text_color()));
        ui.label(RichText::new(value).color(text_primary_color()));
    });
}

fn execution_state_line(ui: &mut Ui, status: &str) {
    ui.horizontal_wrapped(|ui| {
        ui.label(RichText::new("执行态").small().color(subtle_text_color()));
        ui.colored_label(status_color(status), runtime_state_text(status));
    });
}

fn path_list(ui: &mut Ui, id: &'static str, paths: &[String]) {
    if paths.is_empty() {
        ui.label(RichText::new("未选择文件。 ").color(subtle_text_color()));
        return;
    }
    egui::ScrollArea::vertical()
        .id_salt(id)
        .max_height(180.0)
        .show(ui, |ui| {
            for path in paths {
                ui.monospace(path);
            }
        });
}

fn candidate_table(ui: &mut Ui, items: &[RosterCandidateRead]) {
    egui::Grid::new("roster-candidates-grid")
        .striped(true)
        .min_col_width(80.0)
        .show(ui, |ui| {
            ui.strong("学号");
            ui.strong("姓名");
            ui.strong("置信度");
            ui.strong("状态");
            ui.end_row();
            for item in items {
                ui.label(item.student_no.as_deref().unwrap_or("-"));
                ui.label(&item.name);
                ui.label(format!("{:.2}", item.confidence));
                ui.colored_label(status_color(&item.decision_status), &item.decision_status);
                ui.end_row();
            }
        });
}

fn enrollment_table(ui: &mut Ui, items: &[CourseEnrollmentRead]) {
    egui::Grid::new("enrollments-grid")
        .striped(true)
        .min_col_width(100.0)
        .show(ui, |ui| {
            ui.strong("学号");
            ui.strong("姓名");
            ui.strong("状态");
            ui.end_row();
            for item in items {
                ui.label(item.display_student_no.as_deref().unwrap_or("-"));
                ui.label(&item.display_name);
                ui.colored_label(status_color(&item.status), &item.status);
                ui.end_row();
            }
        });
}

fn submission_table(ui: &mut Ui, items: &[SubmissionRead]) {
    egui::ScrollArea::both()
        .id_salt("submissions-table-scroll")
        .max_height(420.0)
        .show(ui, |ui| {
            egui::Grid::new("submissions-grid")
                .striped(true)
                .min_col_width(110.0)
                .show(ui, |ui| {
                    ui.strong("文件");
                    ui.strong("状态");
                    ui.strong("匹配");
                    ui.strong("置信度");
                    ui.strong("当前路径");
                    ui.end_row();
                    for item in items {
                        ui.label(&item.source_entry_name);
                        ui.colored_label(status_color(&item.status), &item.status);
                        ui.label(item.enrollment_public_id.as_deref().unwrap_or("未匹配"));
                        ui.label(
                            item.match_confidence
                                .map(|value| format!("{value:.2}"))
                                .unwrap_or_else(|| "-".to_owned()),
                        );
                        ui.monospace(shorten(&item.current_path, 72));
                        ui.end_row();
                    }
                });
        });
}

fn review_result_table(
    ui: &mut Ui,
    items: &[ReviewResultRead],
    selected_result_id: &mut Option<String>,
) -> bool {
    let mut changed = false;
    egui::ScrollArea::both()
        .id_salt("review-results-table-scroll")
        .max_height(520.0)
        .show(ui, |ui| {
            egui::Grid::new("review-results-grid")
                .striped(true)
                .min_col_width(110.0)
                .show(ui, |ui| {
                    ui.strong("学号");
                    ui.strong("姓名");
                    ui.strong("文件");
                    ui.strong("分数");
                    ui.strong("状态");
                    ui.end_row();
                    for item in items {
                        let selected = Some(&item.public_id) == selected_result_id.as_ref();
                        if ui
                            .selectable_label(selected, item.student_no.as_deref().unwrap_or("-"))
                            .clicked()
                        {
                            *selected_result_id = Some(item.public_id.clone());
                            changed = true;
                        }
                        ui.label(item.student_name.as_deref().unwrap_or("未匹配学生"));
                        ui.label(shorten(&item.source_entry_name, 28));
                        ui.label(
                            item.total_score
                                .map(|value| format!("{value:.1}/{}", item.score_scale))
                                .unwrap_or_else(|| "未评分".to_owned()),
                        );
                        ui.colored_label(status_color(&item.status), &item.status);
                        ui.end_row();
                    }
                });
        });
    changed
}

fn course_review_summary_table(ui: &mut Ui, summary: &CourseReviewSummaryRead) {
    egui::ScrollArea::both()
        .id_salt("course-review-summary-table-scroll")
        .max_height(700.0)
        .show(ui, |ui| {
            egui::Grid::new("course-review-summary-grid")
                .striped(true)
                .min_col_width(120.0)
                .show(ui, |ui| {
                    ui.strong("学号");
                    ui.strong("姓名");
                    for assignment in &summary.assignments {
                        ui.strong(format!("作业{}分数", assignment.seq_no));
                        ui.strong(format!("作业{}简评", assignment.seq_no));
                    }
                    ui.end_row();

                    for row in &summary.rows {
                        ui.label(row.student_no.as_deref().unwrap_or("-"));
                        ui.label(&row.student_name);
                        for cell in &row.results {
                            ui.label(
                                cell.score
                                    .map(|value| format!("{value:.1}"))
                                    .unwrap_or_else(|| "-".to_owned()),
                            );
                            ui.label(
                                cell.summary
                                    .as_deref()
                                    .map(|value| shorten(value, 26))
                                    .unwrap_or_else(|| "-".to_owned()),
                            );
                        }
                        ui.end_row();
                    }
                });
        });
}

fn naming_operation_table(ui: &mut Ui, items: &[crate::models::NamingOperationRead]) {
    egui::ScrollArea::both()
        .id_salt("naming-operations-table-scroll")
        .max_height(460.0)
        .show(ui, |ui| {
            egui::Grid::new("naming-operations-grid")
                .striped(true)
                .min_col_width(130.0)
                .show(ui, |ui| {
                    ui.strong("状态");
                    ui.strong("原路径");
                    ui.strong("目标路径");
                    ui.strong("命令预览");
                    ui.end_row();
                    for item in items {
                        ui.colored_label(status_color(&item.status), &item.status);
                        ui.monospace(shorten(&item.source_path, 58));
                        ui.monospace(shorten(&item.target_path, 58));
                        ui.monospace(item.command_preview.as_deref().unwrap_or("-"));
                        ui.end_row();
                    }
                });
        });
}

fn audit_table(ui: &mut Ui, items: &[AuditEventRead]) {
    egui::ScrollArea::vertical()
        .id_salt("audit-events-scroll")
        .max_height(420.0)
        .show(ui, |ui| {
            for item in items {
                inner_panel_frame().show(ui, |ui| {
                    ui.label(RichText::new(&item.event_type).strong());
                    ui.label(format!(
                        "{} · {} · {}",
                        item.object_type, item.object_public_id, item.created_at
                    ));
                    if let Some(payload) = &item.event_payload_json {
                        json_block(ui, payload);
                    }
                });
                ui.add_space(6.0);
            }
        });
}

fn empty_state(ui: &mut Ui, title: &str, help: &str) {
    inner_panel_frame().show(ui, |ui| {
        ui.label(RichText::new(title).strong().color(text_primary_color()));
        ui.label(RichText::new(help).color(subtle_text_color()));
    });
}

fn json_block(ui: &mut Ui, value: &serde_json::Value) {
    let mut text = serde_json::to_string_pretty(value).unwrap_or_else(|_| value.to_string());
    ui.add(
        TextEdit::multiline(&mut text)
            .id_salt(format!("json-block-{:p}", value))
            .font(egui::TextStyle::Monospace)
            .desired_rows(4)
            .desired_width(f32::INFINITY)
            .interactive(false),
    );
}

fn mode_label(value: &str, options: &[(&str, &str)]) -> String {
    options
        .iter()
        .find(|(key, _)| *key == value)
        .map(|(_, title)| (*title).to_owned())
        .unwrap_or_else(|| value.to_owned())
}

fn is_roster_runtime_active(status: &str) -> bool {
    matches!(status, "queued" | "parsing")
}

fn is_submission_runtime_active(status: &str) -> bool {
    matches!(status, "scanning" | "matching")
}

fn is_review_prep_runtime_active(status: &str) -> bool {
    matches!(
        status,
        "material_parsing"
            | "question_structuring"
            | "answer_generating"
            | "answer_critiquing"
            | "rubric_generating"
    )
}

fn is_review_run_runtime_active(status: &str) -> bool {
    matches!(status, "selecting_assets" | "grading" | "validating")
}

fn runtime_state_text(status: &str) -> &'static str {
    if is_roster_runtime_active(status)
        || is_submission_runtime_active(status)
        || is_review_prep_runtime_active(status)
        || is_review_run_runtime_active(status)
    {
        return "后台运行中";
    }
    match status {
        "failed" => "执行失败",
        "cancelled" => "已停止",
        "needs_review" | "parsed" | "confirmed" | "completed" | "ready" | "applied" => "已完成",
        _ => "待执行",
    }
}

fn status_color(status: &str) -> Color32 {
    match status {
        "active" | "applied" | "ready" | "completed" | "confirmed" | "approved" | "executed"
        | "published" | "renamed" | "finalized" | "validated" | "parsed" => success_color(),
        "draft"
        | "pending"
        | "queued"
        | "running"
        | "generated"
        | "pending_approval"
        | "executing"
        | "naming_ready"
        | "reviewing"
        | "parsing"
        | "scanning"
        | "matching"
        | "material_parsing"
        | "question_structuring"
        | "answer_generating"
        | "answer_critiquing"
        | "rubric_generating"
        | "selecting_assets"
        | "grading"
        | "validating"
        | "needs_review" => warning_color(),
        "failed"
        | "error"
        | "rejected"
        | "conflicted"
        | "needs_manual_review"
        | "partial_failed"
        | "unmatched" => danger_color(),
        "cancelled" => muted_chip_color(),
        _ => muted_chip_color(),
    }
}

fn canvas_color() -> Color32 {
    Color32::from_rgb(244, 246, 249)
}

fn toolbar_color() -> Color32 {
    Color32::from_rgb(250, 251, 253)
}

fn sidebar_color() -> Color32 {
    Color32::from_rgb(238, 241, 246)
}

fn surface_color() -> Color32 {
    Color32::from_rgb(255, 255, 255)
}

fn surface_alt_color() -> Color32 {
    Color32::from_rgb(248, 250, 252)
}

fn selected_surface_color() -> Color32 {
    Color32::from_rgb(239, 246, 255)
}

fn border_color() -> Color32 {
    Color32::from_rgb(221, 226, 235)
}

fn soft_border_color() -> Color32 {
    Color32::from_rgb(231, 235, 242)
}

fn text_primary_color() -> Color32 {
    Color32::from_rgb(28, 33, 42)
}

fn subtle_text_color() -> Color32 {
    Color32::from_rgb(104, 113, 128)
}

fn accent_color() -> Color32 {
    Color32::from_rgb(0, 102, 204)
}

fn accent_soft_color() -> Color32 {
    Color32::from_rgb(143, 190, 242)
}

fn success_color() -> Color32 {
    Color32::from_rgb(42, 130, 88)
}

fn warning_color() -> Color32 {
    Color32::from_rgb(193, 128, 46)
}

fn danger_color() -> Color32 {
    Color32::from_rgb(190, 73, 72)
}

fn muted_chip_color() -> Color32 {
    Color32::from_rgb(132, 141, 156)
}

fn soft_tint(color: Color32) -> Color32 {
    Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), 26)
}

fn card_shadow() -> Shadow {
    Shadow {
        offset: [0, 8],
        blur: 20,
        spread: 0,
        color: Color32::from_black_alpha(16),
    }
}

fn chip_shadow() -> Shadow {
    Shadow {
        offset: [0, 3],
        blur: 10,
        spread: 0,
        color: Color32::from_black_alpha(10),
    }
}

fn trimmed_option(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_owned())
    }
}

fn parse_i64_setting(value: &str, label: &str) -> Result<i64, String> {
    value
        .trim()
        .parse::<i64>()
        .map_err(|_| format!("{label}必须是整数。"))
}

fn parse_f64_setting(value: &str, label: &str) -> Result<f64, String> {
    value
        .trim()
        .parse::<f64>()
        .map_err(|_| format!("{label}必须是数字。"))
}

fn format_compact_f64(value: f64) -> String {
    if value.fract().abs() < f64::EPSILON {
        format!("{value:.0}")
    } else {
        format!("{value:.1}")
    }
}

fn shorten(value: &str, limit: usize) -> String {
    if value.chars().count() <= limit {
        return value.to_owned();
    }
    let mut text: String = value.chars().take(limit.saturating_sub(1)).collect();
    text.push('…');
    text
}

fn push_unique_path(paths: &mut Vec<String>, path: String) {
    if !paths.contains(&path) {
        paths.push(path);
    }
}

fn detect_backend_dir() -> PathBuf {
    std::env::current_dir()
        .ok()
        .map(|cwd| {
            if cwd.file_name().and_then(|name| name.to_str()) == Some("frontend") {
                cwd.parent().unwrap_or(&cwd).join("backend")
            } else {
                cwd.join("backend")
            }
        })
        .unwrap_or_else(|| PathBuf::from("backend"))
}

fn spawn_backend_reader<R: Read + Send + 'static>(
    reader: R,
    sender: Sender<WorkerEvent>,
    prefix: &'static str,
) {
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
                        .send(WorkerEvent::BackendLogLine(format!(
                            "[{prefix}] 读取日志失败：{err}"
                        )))
                        .ok();
                    break;
                }
            }
        }
    });
}
