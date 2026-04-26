# 架构说明

## 总体结构

当前实现采用“本地服务 + 本地界面”的方式：

1. `FastAPI` 作为统一入口，负责文件导入、规则管理、审阅任务 API
2. `SQLite` 负责持久化学生、规则、审阅任务和结果
3. `LangGraph` 负责答题 / 审阅工作流编排
4. `rapidocr-onnxruntime` 负责图片与内嵌图片 OCR
5. 后端内置 Web 控制台，便于直接联调

## 目录职责

### `backend/src/backend/api.py`

- 提供 REST API
- 挂载本地控制台
- 初始化默认规则

### `backend/src/backend/models.py`

- `Student`：学生名单
- `RenameRule`：改名规则
- `ReviewJob`：审阅任务
- `Submission`：单个提交文件与审阅结果

### `backend/src/backend/services/student_import.py`

- 处理 `pdf / csv / xlsx / xls` 名单文件
- 自动识别“姓名 / 学号 / 班级”列
- 在 `auto` 模式下，可在本地解析不可靠时回退到名单布局识别 Agent
- Agent 不直接输出名单，而是输出数据行范围和字段位置，再由 Python 抽取

### `backend/src/backend/services/rename_service.py`

- 根据学生名单匹配文件名
- 基于模板预览改名结果
- 执行批量改名

### `backend/src/backend/services/document_parser.py`

- 提取 `txt / md / docx / pdf / 图片` 正文
- OCR 图片文件
- OCR Word / PDF 内嵌图片
- 提供视觉审阅所需的图像资产

### `backend/src/backend/services/review_graph.py`

- 用 `LangGraph` 串联两个节点：
  - 参考答案准备
  - 学生作答审阅
- 未配置大模型时，走启发式评分
- 配置 OpenAI 兼容接口后，可切换到真实 LLM
- 当审阅模式为 `agent_vision` 时，可直接对图片型作业做视觉评分

### `backend/src/backend/models.py`

- `SubmissionLog`：记录每份作业的处理阶段日志
- `Submission`：新增学生匹配方式、匹配置信度、100 分制字段

### `backend/src/backend/ui/`

- 内置 Web 控制台
- 覆盖名单导入、规则创建、改名、审阅任务查看

## 当前能力边界

当前版本已经能跑通主流程，但还不是最终生产态：

- OCR 已接通，但复杂扫描件、手写体、低清图片仍可能识别不稳
- 未配置大模型时，审阅采用启发式逻辑，更适合联调而不是正式评分
- 视觉评分依赖 OpenAI 兼容多模态模型能力
- 当前界面是内置 Web 控制台，不是 Rust 桌面端

## 下一阶段建议

### 阶段 2：Rust 桌面端

- 用 `egui` 或 `tauri` 做桌面外壳
- 接后端本地 API
- 增加文件夹选择、拖放、进度反馈

### 阶段 3：审阅增强

- 引入可配置的答题 Agent
- 引入多评分维度 Rubric
- 支持批注定位、错误证据片段、审阅报告导出

### 阶段 4：作业解析增强

- 增加扫描件质量检测
- 增加表格、公式、代码块专项解析
- 增加 PDF/Word 图片切片与多模态复核
