# 助教 Agent 后端

当前后端已经重构为“课程化、多阶段、多 Agent、可审批、可审计”的新架构。

它不再只是“导入名单 + 改名 + 审阅”的薄脚本集合，而是一个围绕课程生命周期运行的本地后端系统。

## 技术栈

- `FastAPI`
- `SQLAlchemy 2.x`
- `SQLite`
- `LangGraph`
- `langchain-openai`
- `rapidocr-onnxruntime`
- `python-docx / python-pptx / pypdf / pillow / pandas`

## 当前架构

```text
backend/src/backend/
  api/
    routes/
      courses.py
      rosters.py
      assignments.py
      submissions.py
      naming.py
      review_prep.py
      review_run.py
      approvals.py
      audits.py
  agents/
    base.py
    contracts.py
    course_init_agent.py
    submission_match_agent.py
    naming_policy_agent.py
    review_material_parser_agent.py
    answer_generator_agent.py
    answer_critic_agent.py
    answer_judge_agent.py
    asset_selector_agent.py
    grading_agent.py
    grading_validator_agent.py
  core/
  db/
    migrations/
    repositories/
  domain/
    models/
    enums.py
    state_machine.py
  graphs/
    course_init_graph.py
    submission_import_graph.py
    naming_plan_graph.py
    review_prep_graph.py
    submission_review_graph.py
    review_run_parent_graph.py
  infra/
    file_ops/
    llm/
    observability/
    storage/
    tool_runner/
  schemas/
  services/
```

## 核心领域对象

当前主要表包括：

- `course`
- `person`
- `course_enrollment`
- `roster_import_batch`
- `roster_candidate_row`
- `assignment`
- `submission_import_batch`
- `submission`
- `submission_asset`
- `submission_match_candidate`
- `naming_policy`
- `naming_plan`
- `naming_operation`
- `review_prep`
- `review_question_item`
- `review_answer_generation_round`
- `review_run`
- `review_result`
- `review_item_result`
- `asset_selection_result`
- `approval_task`
- `approval_item`
- `agent_run`
- `tool_call_log`
- `audit_event`

## LangGraph 主流程

当前后端使用真正的 `compiled.invoke` 跑图，不再回退到顺序伪执行。

已接入的主图：

1. `course_init_graph`
   - 名单材料 -> 名单抽取 -> 候选落库

2. `submission_import_graph`
   - 目录扫描 -> 提交匹配 -> 提交落库

3. `naming_plan_graph`
   - 规范命名 -> 改名计划

4. `review_prep_graph`
   - 题目材料解析 -> 多轮答案生成/审查/裁决 -> 题目基线落库

5. `review_run_parent_graph`
   - 按 `submission` 启动子图

6. `submission_review_graph`
   - 文件筛选 -> 文档解析 -> 评分 -> 校验 -> 结果落库

## Agent 与结构化输出

所有 Agent 统一通过 `infra/llm/gateway.py` 调模型，并通过 `agents/contracts.py` 做结构化输出约束。

这批 Agent 当前全部已经接入统一网关：

- `course_init_agent`
- `submission_match_agent`
- `naming_policy_agent`
- `review_material_parser_agent`
- `answer_generator_agent`
- `answer_critic_agent`
- `answer_judge_agent`
- `asset_selector_agent`
- `grading_agent`
- `grading_validator_agent`

统一原则：

- Agent 只负责不确定性判断
- Agent 不写数据库
- Agent 不直接做文件副作用操作
- Agent 输出必须先过 Pydantic schema

## 启动

```bash
cd backend
uv sync
uv run backend
```

默认监听：

- 根路径：`http://127.0.0.1:18080/`
- OpenAPI：`http://127.0.0.1:18080/docs`

## LLM 配置

真实 LLM 模式：

```bash
export ZHUJIAO_LLM_BASE_URL="https://your-endpoint/v1"
export ZHUJIAO_LLM_API_KEY="your-key"
export ZHUJIAO_LLM_MODEL="your-model"
```

可选：

```bash
export ZHUJIAO_LLM_TEMPERATURE="0"
export ZHUJIAO_LLM_TIMEOUT_SECONDS="120"
export ZHUJIAO_LLM_MAX_RETRIES="2"
export ZHUJIAO_LLM_JSON_METHOD="json_schema"
```

本地联调模式：

```bash
export ZHUJIAO_MOCK_LLM_ENABLED="1"
```

说明：

- 启用 `mock_llm` 后，后端仍会经过完整 Agent envelope、schema 校验、LangGraph 与审计链路
- 未配置真实 LLM 且未启用 `mock_llm` 时，Agent 相关流程会返回 `503`

## API 分组

课程与名单：

- `POST /courses`
- `GET /courses`
- `GET /courses/{course_public_id}`
- `GET /courses/{course_public_id}/enrollments`
- `POST /courses/{course_public_id}/roster-imports`
- `POST /roster-imports/{batch_public_id}/run`
- `GET /roster-imports/{batch_public_id}`
- `GET /roster-imports/{batch_public_id}/candidates`
- `POST /roster-imports/{batch_public_id}/confirm`
- `POST /roster-imports/{batch_public_id}/apply`

作业与提交：

- `POST /courses/{course_public_id}/assignments`
- `GET /courses/{course_public_id}/assignments`
- `POST /assignments/{assignment_public_id}/submission-imports`
- `POST /submission-imports/{batch_public_id}/run`
- `GET /submission-imports/{batch_public_id}`
- `GET /submission-imports/{batch_public_id}/submissions`
- `POST /submission-imports/{batch_public_id}/confirm`
- `POST /submission-imports/{batch_public_id}/apply`
- `GET /assignments/{assignment_public_id}/submissions`

命名与审批：

- `POST /assignments/{assignment_public_id}/naming-policies`
- `GET /assignments/{assignment_public_id}/naming-policies`
- `POST /assignments/{assignment_public_id}/naming-plans`
- `GET /naming-plans/{plan_public_id}`
- `POST /naming-plans/{plan_public_id}/submit-approval`
- `POST /naming-plans/{plan_public_id}/execute`
- `POST /naming-plans/{plan_public_id}/rollback`
- `GET /approval-tasks/{approval_task_public_id}`
- `POST /approval-tasks/{approval_task_public_id}/approve`
- `POST /approval-tasks/{approval_task_public_id}/reject`
- `POST /approval-tasks/{approval_task_public_id}/execute`

评审初始化与正式评审：

- `POST /assignments/{assignment_public_id}/review-preps`
- `POST /review-preps/{review_prep_public_id}/run`
- `GET /review-preps/{review_prep_public_id}`
- `GET /review-preps/{review_prep_public_id}/questions`
- `PATCH /review-question-items/{item_public_id}`
- `POST /review-preps/{review_prep_public_id}/confirm`
- `POST /assignments/{assignment_public_id}/review-runs`
- `POST /review-runs/{review_run_public_id}/start`
- `GET /review-runs/{review_run_public_id}`
- `GET /review-runs/{review_run_public_id}/results`
- `PATCH /review-results/{review_result_public_id}/manual-review`
- `POST /review-runs/{review_run_public_id}/retry-failed`
- `POST /review-runs/{review_run_public_id}/publish`

审计查询：

- `GET /agent-runs`
- `GET /agent-runs/{agent_run_public_id}`
- `GET /agent-runs/{agent_run_public_id}/tool-calls`
- `GET /courses/{course_public_id}/audit-events`
- `GET /submissions/{submission_public_id}/audit-events`
- `GET /objects/{object_type}/{object_public_id}/logs`

## 关键约束

- Agent 不允许直接写数据库
- Agent 不允许直接执行重命名、删除、覆盖等副作用操作
- 所有高风险动作先转 `approval_task`
- 文件副作用必须由主程序执行器完成
- 默认保留 `agent_run / tool_call_log / audit_event` 留痕

## 当前建议

如果你要继续实现下一轮能力，优先顺序建议是：

1. 接入真实多模态模型与正式提示词版本管理
2. 为每条主图补更细的集成测试
3. 将前端切到新的课程化 API
