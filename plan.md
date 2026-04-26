# 后端整体重构实施计划

## 1. 文档目的

本文件用于指导当前助教项目的后端整体重构，目标是将现有“单体式学生/改名/审阅逻辑”升级为“课程化、多阶段、多 Agent、可审批、可审计、可回放”的后端系统。

本计划基于以下两份前置设计文档整理：

- [后端新数据库模型 + 状态机 + API 草案](./后端新数据库模型 + 状态机 + API 草案.md)
- [LangGraph 工作流](./LangGraph 工作流.md)

本文档不是产品宣传文档，而是工程执行文档。重点是：

1. 明确重构目标、边界和非目标
2. 明确新的数据库模型和模块拆分落地顺序
3. 明确每个阶段应实现的 Graph、Agent、API、日志和审批能力
4. 明确验收标准、风险和迁移策略

---

## 2. 总体目标

后端重构完成后，应达到以下目标：

1. 所有业务围绕“课程”组织，而不是把学生、作业、评分平铺在一个全局空间中
2. 课程初始化、作业导入、命名纠正、评审初始化、正式评审应具备独立状态机
3. 所有高风险操作必须可审批、可回滚、可审计
4. 所有 Agent 输出必须结构化、可校验、可重试、可落库
5. 所有评审结果必须可追溯到题目版本、答案版本、评分规范版本、模型版本、提示词版本、工具调用记录
6. 正式评审必须支持并行，但并行粒度限定在 submission 级别
7. 所有日志必须支持留痕，包括 Agent 运行、工具调用、审批、文件操作和最终业务结果

---

## 3. 重构边界

### 3.1 本轮重构范围

本轮重构聚焦后端，不直接重写前端界面。前端只在后端稳定后再适配。

本轮范围包括：

1. 新数据库模型设计与迁移
2. 新状态机与业务编排
3. `LangGraph` 工作流落地
4. Agent 输入输出 Schema 定义与实现
5. API 重新分层与重写
6. 审批、审计、日志体系
7. 文件操作执行器与受控工具层

### 3.2 本轮非目标

本轮不优先处理以下内容：

1. 最终前端页面重写
2. 完整的成绩发布界面体验
3. 全量历史数据自动兼容迁移
4. 一开始就覆盖所有奇异文件格式
5. 一开始就支持超复杂多题多文件多层嵌套的极端场景

### 3.3 不可违反的底线

1. Agent 不允许直接写数据库
2. Agent 不允许直接执行重命名、删除、覆盖等副作用操作
3. 所有副作用操作必须通过主程序执行器
4. 所有高风险副作用操作必须先生成 `approval_task`
5. 不记录模型私有思维链，但必须记录提示词版本、结构化输入输出、工具调用和错误信息

---

## 4. 重构原则

### 4.1 架构原则

1. 领域模型先行，Agent 编排后置
2. 数据结构稳定优先于提示词技巧
3. 业务事实与 Agent 过程分离
4. 文件操作、审计、审批与模型调用解耦
5. 新后端默认以“可复现”和“可回放”为设计中心

### 4.2 Agent 原则

1. Agent 只负责不确定性任务
2. 能用规则稳定完成的事情不交给 Agent
3. Agent 输出必须是 JSON
4. Agent 输出必须经过 Schema 校验
5. Agent 输出必须带 `confidence`、`warnings`、`needs_review`
6. Graph 必须具备最大轮次和最大重试限制

### 4.3 工程原则

1. 先并行引入新表和新模块，再切流量，不直接在旧逻辑上堆叠
2. 每个阶段必须有明确验收边界
3. 每个阶段必须具备最小测试集合
4. 每个阶段必须保留回退路径

---

## 5. 目标后端结构

建议将当前后端逐步重组为以下结构：

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
  domain/
    models/
    enums/
    value_objects/
  db/
    base.py
    session.py
    migrations/
    repositories/
  graphs/
    course_init_graph.py
    submission_import_graph.py
    naming_plan_graph.py
    review_prep_graph.py
    review_run_parent_graph.py
    submission_review_graph.py
  agents/
    course_init_agent.py
    submission_grouping_agent.py
    submission_match_agent.py
    naming_policy_agent.py
    naming_exception_agent.py
    review_material_parser_agent.py
    answer_generator_agent.py
    answer_critic_agent.py
    answer_judge_agent.py
    rubric_generator_agent.py
    asset_selector_agent.py
    grading_agent.py
    grading_validator_agent.py
  schemas/
    common.py
    course_init.py
    submission_import.py
    naming.py
    review_prep.py
    review_run.py
  services/
    course_service.py
    roster_service.py
    assignment_service.py
    submission_service.py
    naming_service.py
    review_prep_service.py
    review_run_service.py
    approval_service.py
    audit_service.py
  infra/
    llm/
    storage/
    parsers/
    tool_runner/
    file_ops/
    observability/
```

说明：

1. `graphs/` 负责状态流转
2. `agents/` 负责结构化语义节点
3. `services/` 负责领域动作与事务协调
4. `db/repositories/` 负责数据访问
5. `infra/` 负责 LLM、文件、工具、日志等基础设施

---

## 6. 新数据库模型实施范围

本轮应引入的新实体如下：

1. `course`
2. `person`
3. `course_enrollment`
4. `roster_import_batch`
5. `roster_candidate_row`
6. `assignment`
7. `submission_import_batch`
8. `submission`
9. `submission_asset`
10. `submission_match_candidate`
11. `naming_policy`
12. `naming_plan`
13. `naming_operation`
14. `review_prep`
15. `review_question_item`
16. `review_answer_generation_round`
17. `review_run`
18. `review_result`
19. `review_item_result`
20. `asset_selection_result`
21. `approval_task`
22. `approval_item`
23. `agent_run`
24. `tool_call_log`
25. `audit_event`

旧表 `students / rename_rules / review_jobs / submissions / submission_logs` 不应立刻删除。建议分三步处理：

1. 先保留旧表，新增新表
2. 新 API 与新 Graph 只写新表
3. 旧逻辑完全退出后，再做旧表归档或删除

---

## 7. 状态机实施原则

每个主流程独立维护状态机，不做“一个大总状态机”。

必须先实现以下状态机：

1. `course.status`
2. `roster_import_batch.status`
3. `assignment.status`
4. `submission_import_batch.status`
5. `submission.status`
6. `naming_policy.status`
7. `naming_plan.status`
8. `naming_operation.status`
9. `review_prep.status`
10. `review_question_item.status`
11. `review_answer_generation_round.status`
12. `review_run.status`
13. `review_result.status`
14. `approval_task.status`
15. `agent_run.status`

每个状态机都必须具备：

1. 合法状态枚举
2. 合法状态迁移表
3. 非法迁移保护
4. 状态变更审计事件
5. 状态变更时间戳

---

## 8. Agent 清单与实施优先级

### 8.1 第一阶段必须实现的 Agent

1. `course_init_agent`
2. `submission_match_agent`
3. `naming_policy_agent`
4. `review_material_parser_agent`
5. `answer_generator_agent`
6. `answer_critic_agent`
7. `answer_judge_agent`
8. `asset_selector_agent`
9. `grading_agent`
10. `grading_validator_agent`

### 8.2 第二阶段可补充的 Agent

1. `submission_grouping_agent`
2. `naming_exception_agent`
3. 更强的 `rubric_generator_agent`
4. 结果仲裁 Agent
5. 异常恢复 Agent

### 8.3 明确不是 Agent 的模块

1. 文件上传与存储
2. 压缩包解压
3. 文件哈希计算
4. Schema 校验
5. 数据库写入
6. 审批创建与执行
7. 文件重命名执行器
8. 审计日志写入器

---

## 9. 分阶段实施计划

## 阶段 0：重构准备与冻结边界

### 目标

为后续大改建立新的目录、配置、枚举和迁移基线，冻结旧后端新增功能。

### 任务

1. 冻结旧后端新增功能开发
2. 新建后端重构分支
3. 创建新目录骨架
4. 拆出统一配置模块、统一日志模块、统一错误模块
5. 定义通用枚举与通用 Schema 包裹层
6. 建立迁移目录与迁移规范
7. 建立 `agent_run / tool_call_log / audit_event` 的最小通用模型

### 产出

1. 新目录结构
2. 统一配置与日志基础设施
3. 第一版迁移框架
4. 第一版统一 Agent 输入输出基类

### 验收标准

1. 新目录可导入
2. 新迁移机制可执行
3. `agent_run` 与 `audit_event` 可正常写入测试数据

---

## 阶段 1：数据库骨架重构

### 目标

先把业务骨架立起来，不急着接多模态 Agent。

### 任务

1. 新建课程相关表
2. 新建名单导入相关表
3. 新建作业与提交相关表
4. 新建命名、评审初始化、正式评审相关表
5. 新建审批与审计相关表
6. 为关键表增加唯一约束与索引
7. 建立 Repository 层
8. 编写新旧表并行存在时的最小适配策略

### 产出

1. 全量新表迁移脚本
2. 新领域模型
3. Repository 接口

### 验收标准

1. 新表可完整创建
2. 关键约束与索引通过测试
3. 核心实体可完成最小 CRUD

---

## 阶段 2：课程初始化链路

### 目标

实现课程创建、名单导入、候选识别、人工确认、名单生效全流程。

### Graph

实现 `course_init_graph`

### 任务

1. 完成 `course / person / course_enrollment / roster_import_batch / roster_candidate_row` 相关 Service 和 Repository
2. 落地 `course_init_agent`
3. 实现名单材料上传与预览提取
4. 实现 Agent 结构化输出校验
5. 实现名单冲突检测
6. 实现人工确认接口
7. 实现确认后写入课程名单
8. 记录审计与 Agent 运行日志

### API

1. `POST /courses`
2. `GET /courses`
3. `POST /courses/{course_id}/roster-imports`
4. `POST /roster-imports/{batch_id}/run`
5. `GET /roster-imports/{batch_id}`
6. `GET /roster-imports/{batch_id}/candidates`
7. `POST /roster-imports/{batch_id}/confirm`
8. `POST /roster-imports/{batch_id}/apply`

### 验收标准

1. 能创建课程
2. 能上传名单材料
3. Agent 能输出结构化候选名单
4. 低置信条目可人工确认
5. 课程名单能正式写入并可查询

---

## 阶段 3：作业定义与作业导入链路

### 目标

建立“某课程的第几次作业”以及“某学生在该作业下的提交记录”。

### Graph

实现 `submission_import_graph`

### 任务

1. 实现 `assignment / submission_import_batch / submission / submission_asset / submission_match_candidate`
2. 实现作业创建接口
3. 实现作业文件夹扫描与入口清单生成
4. 先用规则版入口分组逻辑
5. 落地 `submission_match_agent`
6. 实现高置信自动确认与低置信人工确认
7. 实现提交记录入库
8. 建立提交与学生、作业的稳定绑定关系

### API

1. `POST /courses/{course_id}/assignments`
2. `GET /courses/{course_id}/assignments`
3. `POST /assignments/{assignment_id}/submission-imports`
4. `POST /submission-imports/{batch_id}/run`
5. `GET /submission-imports/{batch_id}`
6. `GET /submission-imports/{batch_id}/submissions`
7. `POST /submission-imports/{batch_id}/confirm`
8. `POST /submission-imports/{batch_id}/apply`
9. `GET /assignments/{assignment_id}/submissions`

### 验收标准

1. 能定义一次作业
2. 能导入一个作业文件夹
3. 能得到提交候选和学生匹配结果
4. 低置信匹配可人工修正
5. 一名学生在某次作业下只对应一个当前提交记录

---

## 阶段 4：命名规范与审批执行链路

### 目标

让命名规划和真正执行重命名彻底分离。

### Graph

实现 `naming_plan_graph`

### 任务

1. 实现 `naming_policy / naming_plan / naming_operation`
2. 落地 `naming_policy_agent`
3. 第二阶段可接入 `naming_exception_agent`
4. 根据提交记录和命名规范生成命名计划
5. 生成 `approval_task`
6. 实现审批通过后的受控执行器
7. 实现改名前后审计与回滚信息记录

### API

1. `POST /assignments/{assignment_id}/naming-policies`
2. `GET /assignments/{assignment_id}/naming-policies`
3. `POST /assignments/{assignment_id}/naming-plans`
4. `GET /naming-plans/{plan_id}`
5. `POST /naming-plans/{plan_id}/submit-approval`
6. `POST /naming-plans/{plan_id}/execute`
7. `POST /naming-plans/{plan_id}/rollback`
8. `GET /approval-tasks/{approval_task_id}`
9. `POST /approval-tasks/{approval_task_id}/approve`
10. `POST /approval-tasks/{approval_task_id}/reject`

### 验收标准

1. 能把自然语言规范转为模板
2. 能生成批量改名计划
3. 改名操作必须先审批
4. 审批通过后才真正执行文件改名
5. 每条改名操作都有留痕和回滚信息

---

## 阶段 5：评审初始化链路

### 目标

把题目、答案、评分规范的准备过程正式版本化。

### Graph

实现 `review_prep_graph`

### 任务

1. 实现 `review_prep / review_question_item / review_answer_generation_round`
2. 落地 `review_material_parser_agent`
3. 落地 `answer_generator_agent`
4. 落地 `answer_critic_agent`
5. 落地 `answer_judge_agent`
6. 第一阶段可先用规则版 `rubric_generator_agent`
7. 实现题目材料上传与预览提取
8. 实现多轮答案生成与纠错循环
9. 实现题目、答案、rubric 的草稿版本保存
10. 实现人工确认后标记 `review_prep_ready`

### API

1. `POST /assignments/{assignment_id}/review-preps`
2. `POST /review-preps/{review_prep_id}/run`
3. `GET /review-preps/{review_prep_id}`
4. `GET /review-preps/{review_prep_id}/questions`
5. `PATCH /review-question-items/{item_id}`
6. `POST /review-preps/{review_prep_id}/confirm`

### 验收标准

1. 能上传题目和答案材料
2. 能拆分出单题结构
3. 能得到参考答案和评分规范草稿
4. 多轮答案纠错不会无限循环
5. 人工确认后可形成正式评审基线版本

---

## 阶段 6：正式评审链路

### 目标

建立以 submission 为粒度的并行评审体系，并把评分与文件筛选解耦。

### Graph

实现 `review_run_parent_graph`

实现 `submission_review_graph`

### 任务

1. 实现 `review_run / review_result / review_item_result / asset_selection_result`
2. 落地 `asset_selector_agent`
3. 落地 `grading_agent`
4. 落地 `grading_validator_agent`
5. 接入现有文档解析和压缩包解析能力，但改造成新表结构下运行
6. 实现 submission 级子图并行
7. 实现结果入库、低置信转人工复核、失败重试
8. 实现 `draft -> validated -> finalized -> published` 结果生命周期

### API

1. `POST /assignments/{assignment_id}/review-runs`
2. `POST /review-runs/{review_run_id}/start`
3. `GET /review-runs/{review_run_id}`
4. `GET /review-runs/{review_run_id}/results`
5. `PATCH /review-results/{result_id}/manual-review`
6. `POST /review-runs/{review_run_id}/retry-failed`
7. `POST /review-runs/{review_run_id}/publish`

### 验收标准

1. 每份提交可单独进入子图评审
2. 辅助 Agent 能选出有效文件并记录理由
3. 评分 Agent 能输出结构化分数和理由
4. 校验 Agent 能发现不一致并转人工复核
5. 最终分数与理由可稳定落库并可查询

---

## 阶段 7：审计、运维与前端适配

### 目标

补齐统一查询、统一日志与前端接入层。

### 任务

1. 补全统一 `audit_event` 查询接口
2. 补全统一 `agent_run` 与 `tool_call_log` 查询接口
3. 补全课程级、作业级、提交级审计视图
4. 输出前端适配所需的聚合查询接口
5. 清理旧 API，标记废弃
6. 视情况将旧表迁移为只读归档

### API

1. `GET /agent-runs`
2. `GET /agent-runs/{agent_run_id}`
3. `GET /agent-runs/{agent_run_id}/tool-calls`
4. `GET /courses/{course_id}/audit-events`
5. `GET /submissions/{submission_id}/audit-events`
6. `GET /objects/{object_type}/{object_id}/logs`

### 验收标准

1. 课程、作业、提交、评审运行都能查到对应日志
2. 每个高风险操作都能追到审批记录
3. 前端已经具备接新 API 的最小读取面

---

## 10. 统一日志与审计计划

### 必须记录的内容

1. Graph 名称、阶段名称、运行状态
2. Agent 名称、模型名、提示词版本
3. Agent 结构化输入引用和结构化输出引用
4. 工具调用参数、返回值、退出码、耗时
5. 文件重命名前后路径与文件哈希
6. 审批发起、审批通过、审批拒绝、审批执行
7. 最终业务结果写入与状态流转

### 不记录的内容

1. 模型私有思维链
2. 与业务无关的冗余原始大文本
3. 无结构的随意调试打印

### 存储建议

1. 结构化元数据进 SQLite
2. 大文本、大 JSON、模型原始响应可落到 `artifacts/`
3. 数据库只存引用路径或对象标识

---

## 11. 审批与执行器计划

### 必须审批的操作

1. 批量重命名
2. 删除文件
3. 覆盖已有文件
4. 批量替换课程名单
5. 批量修正学生归属
6. 已发布成绩重算覆盖
7. 结果正式发布

### 执行器职责

1. 接收 `approval_task` 和 `approval_item`
2. 生成命令预览
3. 校验路径安全性
4. 执行文件操作
5. 写回执行结果和回滚信息
6. 写入审计事件

### 风险控制

1. 默认不做真删除，优先移动到隔离区
2. 默认不覆盖已有目标文件，先标记冲突
3. 所有执行器必须在受控根目录内工作

---

## 12. 数据迁移与切换策略

### 迁移策略

1. 新表先建，不覆盖旧表
2. 新 API 逐步切到新表
3. 旧功能在新链路完成前保持只读或最小维护
4. 关键业务稳定后，再考虑旧表数据导入新表

### 推荐切换顺序

1. 先切课程初始化
2. 再切作业导入
3. 再切命名修正
4. 再切评审初始化
5. 最后切正式评审

### 回退策略

1. 每个阶段完成后保留回退开关
2. 新旧 API 可并存一段时间
3. 高风险阶段必须有数据库备份与运行快照

---

## 13. 测试计划

### 单元测试

1. Repository 基本 CRUD
2. 状态机合法迁移与非法迁移
3. Schema 校验
4. 命名模板渲染
5. 审批任务状态流转

### 集成测试

1. 课程初始化全链路
2. 作业导入全链路
3. 命名规划到审批执行全链路
4. 评审初始化多轮答案纠错链路
5. 正式评审单份 submission 子图链路

### 端到端测试

1. 一门课程从初始化到作业导入
2. 一次作业从命名规范到评审初始化
3. 一批作业从正式评审到人工复核

---

## 14. 风险点

1. 旧模型与新模型并存期间，概念容易混淆
2. 一开始就让太多 Agent 参与，会导致复杂度过高
3. 多模态材料解析可能带来大文本和高成本问题
4. 评审初始化的多轮答案纠错如果无边界，容易失控
5. 文件操作执行器如果边界没锁死，会有较大风险
6. 正式评审并行如果没有限流，容易打爆模型配额和本地资源

---

## 15. 待确认项

以下问题建议在正式编码前由产品侧或你明确拍板：

1. 学生身份是否全局唯一
2. 作业轮次是否允许 Agent 自动猜测后人工确认
3. 重命名是直接改原文件，还是支持输出规范副本目录
4. 评审初始化结果是否必须人工确认后才能正式评审
5. 正式评审结果落库后是否允许直接发布，还是必须二次确认
6. 日志中是否允许长期保存学生原始文件和图像引用

---

## 16. 第一阶段最小可交付范围

若需要先做一个最小可交付版本，建议收缩为以下范围：

1. 新数据库骨架
2. 课程创建与名单初始化
3. 作业定义与作业导入
4. 命名规划与审批
5. 评审初始化单题版本
6. 正式评审单 submission 版本
7. 统一日志与审批查询

暂缓项：

1. 多入口智能分组 Agent
2. 高级 naming exception 检测
3. 多题复杂评分聚合
4. 已发布结果的复杂回滚
5. 前端大改

---

## 17. 推荐执行顺序总结

1. 阶段 0：建基线
2. 阶段 1：立新表
3. 阶段 2：做课程初始化
4. 阶段 3：做作业导入
5. 阶段 4：做命名规划与审批
6. 阶段 5：做评审初始化
7. 阶段 6：做正式评审
8. 阶段 7：补日志、审计、前端适配

简短结论：

先把课程、作业、提交、评审、审批、审计这些稳定骨架立起来，再把 Agent 一个个挂到正确的节点上。  
任何试图先写“大而全多 Agent”再补骨架的做法，都会导致系统不可控、不可追溯、不可维护。
