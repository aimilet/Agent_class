# 自动化改作业助教 Agent

这是一个本地优先的助教多 Agent 系统，当前主线已经切到“课程化、多阶段、可审批、可审计、可回放”的新后端架构。

当前仓库包含三部分：

- `backend/`：`FastAPI + SQLAlchemy + SQLite + LangGraph` 后端
- `frontend/`：`eframe/egui` 原生桌面前端
- `dist/windows/zhujiao-agent.exe`：已构建的 Windows 桌面可执行文件

## 当前后端主流程

后端现在围绕“课程”组织，而不是把学生、作业、评分平铺在全局空间中。

已落地的主流程如下：

1. 课程初始化
   - 创建课程
   - 上传名单材料
   - 调用 `course_init_agent`
   - 生成候选名单
   - 人工确认并写入课程名单

2. 作业导入
   - 创建课程下的第 `N` 次作业
   - 扫描作业目录
   - 调用 `submission_match_agent`
   - 建立提交记录、学生匹配候选与提交资产

3. 命名规划与审批
   - 调用 `naming_policy_agent`
   - 生成命名模板和批量改名计划
   - 先创建 `approval_task`
   - 审批通过后才执行真实重命名

4. 评审初始化
   - 上传题目/答案/评分材料
   - 调用 `review_material_parser_agent`
   - 调用 `answer_generator / answer_critic / answer_judge`
   - 形成单题级题干、参考答案和 rubric 草稿

5. 正式评审
   - 创建 `review_run`
   - 以 `submission` 为粒度调用子图
   - 调用 `asset_selector_agent`
   - 调用 `grading_agent` 和 `grading_validator_agent`
   - 结果写入数据库并进入人工复核/发布链路

6. 审批与审计
   - 高风险动作必须先审批
   - `agent_run / tool_call_log / audit_event` 全链路留痕

## Agent 与 LLM

当前 Agent 已经统一切到“提示词 + 结构化输出 schema + LLM gateway”的模式，不再直接在主流程里使用旧的启发式 Agent。

已接入的新 Agent 包括：

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

运行模式有两种：

1. 真实 LLM / 多模态模式
   - 通过 `langchain-openai` 调 OpenAI 兼容接口
   - 需要配置模型地址、密钥和模型名

2. `mock_llm` 联调模式
   - 不依赖真实模型
   - 仍走统一结构化调用链路
   - 适合本地冒烟和图执行联调

## 快速启动

先准备后端环境：

```bash
cd backend
uv sync
```

手动启动后端：

```bash
cd backend
uv run backend
```

默认地址：

- API 根路径：`http://127.0.0.1:18080/`
- OpenAPI：`http://127.0.0.1:18080/docs`

启动桌面端：

```bash
cd frontend
source "$HOME/.cargo/env"
cargo run
```

桌面端默认连接：

```text
http://127.0.0.1:18080
```

Windows 可执行文件：

```text
dist/windows/zhujiao-agent.exe
```

## LLM 配置

真实模型模式：

```bash
export ZHUJIAO_LLM_BASE_URL="https://your-endpoint/v1"
export ZHUJIAO_LLM_API_KEY="your-key"
export ZHUJIAO_LLM_MODEL="your-model"
```

可选参数：

```bash
export ZHUJIAO_LLM_TEMPERATURE="0"
export ZHUJIAO_LLM_TIMEOUT_SECONDS="120"
export ZHUJIAO_LLM_MAX_RETRIES="2"
export ZHUJIAO_LLM_JSON_METHOD="json_schema"
```

本地 `mock_llm` 联调：

```bash
export ZHUJIAO_MOCK_LLM_ENABLED="1"
```

说明：

- 未配置真实 LLM 且未启用 `mock_llm` 时，Agent 相关接口会返回 `503`
- `mock_llm` 仍会经过统一 schema 校验、Agent 审计和 LangGraph 流程

## 目录概览

```text
backend/src/backend/
  api/           # 路由与依赖注入
  agents/        # Agent 提示词职责与结构化输出
  core/          # 配置、日志、错误
  db/            # 会话、迁移、Repository
  domain/        # 领域模型、状态机、枚举
  graphs/        # LangGraph 主流程
  infra/         # LLM、存储、文件操作、观测
  schemas/       # API schema 与 Agent envelope
  services/      # 事务协调与业务服务
frontend/src/
  app.rs         # 桌面 UI 主界面
  api.rs         # 桌面端后端通信
```

## 关键约束

- Agent 不直接写数据库
- Agent 不直接执行重命名、删除、覆盖等副作用操作
- 文件变更类动作必须先生成审批任务
- 审批通过后才由主程序执行器落地
- 不保存模型私有思维链，但保存结构化输入输出、工具调用和错误信息

## 相关文档

- [后端新数据库模型 + 状态机 + API 草案](/mnt/f/code_keyan/zhujiao_task/后端新数据库模型%20%2B%20状态机%20%2B%20API%20草案.md)
- [LangGraph 工作流](/mnt/f/code_keyan/zhujiao_task/LangGraph%20工作流.md)
- [plan.md](/mnt/f/code_keyan/zhujiao_task/plan.md)
- [docs/architecture.md](/mnt/f/code_keyan/zhujiao_task/docs/architecture.md)
- [backend/README.md](/mnt/f/code_keyan/zhujiao_task/backend/README.md)
