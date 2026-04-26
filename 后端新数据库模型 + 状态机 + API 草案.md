  一、核心边界

  - Agent 只负责“识别、推断、生成、筛选、评分、解释”这类不确定性任务。
  - 主程序负责“落库、状态流转、权限控制、审批、执行文件操作、审计日志”。
  - 任何重命名、删除、覆盖、批量修正，都不能由 Agent 直接执行，必须先生成 approval_task，你确认后再由受控执行器处理。
  - 任何 Agent 输出都必须先转成结构化 JSON，并通过 schema 校验后才能入库或继续流转。

  二、新数据库模型
  下面我按“实体表”给你一版建议。
  主键我建议内部用 INTEGER，外部 API 额外暴露 public_id，避免直接把自增 id 暴露给前端。

  课程与学生

  - course：课程主表。字段建议有 public_id、course_code、course_name、term、class_label、teacher_name、status、
    active_roster_batch_id、created_at、updated_at。
  - person：全局学生身份表。字段建议有 public_id、student_no_raw、student_no_norm、name_raw、name_norm、created_at。
  - course_enrollment：课程内学生名单。字段建议有 course_id、person_id、display_student_no、display_name、
    source_roster_batch_id、status、created_at。
  - roster_import_batch：一次课程初始化名单导入批次。字段建议有 course_id、source_files_json、parse_mode、status、
    agent_run_id、summary_json、created_at、updated_at。
  - roster_candidate_row：初始化 Agent 提取出的候选名单行。字段建议有 batch_id、source_file、page_no、row_ref、
    student_no、name、confidence、raw_fragment、decision_status、decision_note。

  作业与提交

  - assignment：某门课程的一次作业。字段建议有 course_id、seq_no、title、slug、description、due_at、status、
    review_prep_id、created_at、updated_at。
  - submission_import_batch：一次作业文件夹导入批次。字段建议有 assignment_id、root_path、status、agent_run_id、
    summary_json、created_at、updated_at。
  - submission：一个学生在某次作业下的一份逻辑提交记录。字段建议有 assignment_id、enrollment_id、source_entry_name、
    source_entry_path、matched_by、match_confidence、match_reason、status、canonical_name、current_path、created_at、
    updated_at。
  - submission_asset：提交中真正有价值的文件资产。字段建议有 submission_id、logical_path、real_path、file_hash、
    mime_type、size_bytes、asset_role、selected_by_agent、selected_reason、is_ignored。
  - submission_match_candidate：导入 Agent 给出的候选匹配。字段建议有 submission_id、enrollment_id、confidence、reason、
    rank_order。

  命名规范

  - naming_policy：某次作业当前有效的规范命名策略。字段建议有 assignment_id、template_text、natural_language_rule、
    version_no、created_by_agent_run_id、status。
  - naming_plan：一次命名修正规划。字段建议有 assignment_id、policy_id、status、agent_run_id、approval_task_id、
    summary_json、created_at。
  - naming_operation：每个文件的改名计划与执行结果。字段建议有 plan_id、submission_id、source_path、target_path、
    status、conflict_strategy、command_preview、executed_at、rollback_info_json。

  评审初始化

  - review_prep：某次作业的评审初始化结果。字段建议有 assignment_id、status、agent_run_id、source_materials_json、
    version_no、confirmed_at、created_at。
  - review_question_item：拆分后的单题。字段建议有 review_prep_id、question_no、question_full_text、
    reference_answer_short、reference_answer_full、rubric_text、score_weight、status。
  - review_answer_generation_round：答案生成与纠正的对话轮次。字段建议有 review_prep_id、question_item_id、round_no、
    generator_output、critic_feedback、judge_result、status。

  正式评审

  - review_run：一次正式评审任务。字段建议有 assignment_id、review_prep_id、status、parallelism、summary_json、
    created_at、updated_at。
  - review_result：某份提交的最终评分结果。字段建议有 review_run_id、submission_id、total_score、score_scale、summary、
    decision、confidence、status、result_json、published_at。
  - review_item_result：按单题拆分的评分。字段建议有 review_result_id、question_item_id、score、reason、evidence_json。
  - asset_selection_result：辅助 Agent 选出的有效文件结果。字段建议有 review_run_id、submission_id、
    selected_assets_json、ignored_assets_json、summary、agent_run_id。

  审批与审计

  - approval_task：待你确认的操作计划。字段建议有 object_type、object_id、action_type、status、title、summary、
    command_preview_json、expires_at、approved_at、rejected_at、operator_note。
  - approval_item：审批中的细项。字段建议有 approval_task_id、item_type、before_json、after_json、risk_level。
  - agent_run：一次 Agent 运行的元信息。字段建议有 graph_name、agent_name、stage_name、status、model_name、
    prompt_version、input_ref_json、output_ref_json、error_message、started_at、ended_at。
  - tool_call_log：一次工具调用记录。字段建议有 agent_run_id、tool_name、command_text、arguments_json、stdout_ref、
    stderr_ref、exit_code、status、started_at、ended_at。
  - audit_event：统一审计流。字段建议有 event_type、object_type、object_id、actor_type、actor_id、event_payload_json、
    created_at。

  建议唯一约束

  - course(course_code, term, class_label) 唯一。
  - course_enrollment(course_id, person_id) 唯一。
  - assignment(course_id, seq_no) 唯一。
  - review_question_item(review_prep_id, question_no) 唯一。
  - submission(assignment_id, enrollment_id) 初期建议唯一。
    如果以后要支持同一学生多次补交，再扩成 attempt_no。

  三、状态机
  我建议不要做一个总状态机，而是每个主流程各有自己的状态机。

  1. 课程与名单初始化

  - course.status
  - draft：课程刚创建。
  - initializing：正在导入名单。
  - active：名单确认并生效。
  - archived：课程结束归档。
  - failed：初始化失败但未废弃。
  - roster_import_batch.status
  - uploaded：文件已上传。
  - queued：等待初始化 Agent。
  - parsing：Agent 正在识别。
  - parsed：已得到候选 JSON。
  - needs_review：有低置信条目，等待人工确认。
  - confirmed：名单确认通过。
  - applied：已写入 course_enrollment。
  - failed：识别或落库失败。
  - cancelled：人工取消。

  2. 作业导入

  - assignment.status
  - draft：作业定义刚创建。
  - accepting_submissions：允许导入作业。
  - submissions_imported：已完成一轮导入。
  - naming_ready：可进入命名规范处理。
  - review_prep_ready：评审初始化已确认。
  - reviewing：正式评审中。
  - reviewed：评审结束。
  - published：成绩/结果发布。
  - archived：归档。
  - submission_import_batch.status
  - created
  - scanning
  - matching
  - needs_review
  - confirmed
  - applied
  - failed
  - submission.status
  - discovered：刚从文件夹发现。
  - matched：高置信匹配到学生。
  - ambiguous：存在多个候选。
  - unmatched：无法匹配。
  - confirmed：人工确认归属。
  - naming_pending
  - named
  - review_ready
  - reviewing
  - reviewed
  - published
  - failed
  - ignored

  3. 命名规范

  - naming_policy.status
  - draft
  - active
  - superseded
  - archived
  - naming_plan.status
  - generated
  - pending_approval
  - approved
  - executing
  - applied
  - partially_applied
  - rejected
  - failed
  - rolled_back
  - naming_operation.status
  - planned
  - approved
  - renamed
  - skipped
  - conflicted
  - failed
  - rolled_back

  4. 评审初始化

  - review_prep.status
  - draft
  - material_parsing
  - question_structuring
  - answer_generating
  - answer_critiquing
  - rubric_generating
  - needs_review
  - confirmed
  - ready
  - failed
  - review_question_item.status
  - draft
  - generated
  - revised
  - confirmed
  - disabled
  - review_answer_generation_round.status
  - generated
  - criticized
  - accepted
  - rejected
  答案生成设置“最多 3 到 5 轮生成-批评-判定”，超出就转人工确认。

  1. 正式评审

  - review_run.status
  - queued
  - selecting_assets
  - grading
  - validating
  - needs_review
  - completed
  - partial_failed
  - failed
  - cancelled
  - review_result.status
  - draft
  - validated
  - needs_manual_review
  - finalized
  - published
  - retracted

  6. 审批与日志

  - approval_task.status
  - pending
  - approved
  - rejected
  - expired
  - executing
  - executed
  - partially_executed
  - failed
  - cancelled
  - agent_run.status
  - queued
  - running
  - succeeded
  - failed
  - cancelled
  - timed_out

  四、哪些是 Agent
  下面我直接标注“是 Agent”还是“不是 Agent”。

  是 Agent

  - course_init_agent
    作用：识别 Excel、图片、PDF 名单，输出结构化学生 JSON。
  - submission_import_agent
    作用：识别作业文件夹中的作业轮次线索、学生对应关系、异常情况。
  - naming_policy_agent
    作用：把自然语言规范命名描述转成模板和约束。
  - naming_exception_agent
    作用：发现不规范命名、冲突命名、可疑命名。
  - review_material_parser_agent
    作用：解析题目材料，拆题，抽答案线索，抽 rubric 线索。
  - answer_generator_agent
    作用：根据题目生成参考答案。
  - answer_critic_agent
    作用：质疑参考答案、指出漏洞和缺项。
  - answer_judge_agent
    作用：决定本轮答案是否通过，或是否进入下一轮修正。
  - asset_selector_agent
    作用：从文件夹、压缩包、嵌套目录、杂项文件中挑出真正有价值的作业材料。
  - grading_agent
    作用：对单份学生作业打分并给理由。
  - grading_validator_agent
    作用：检查分数、理由、rubric 是否一致，决定是否需要人工复核。

  不是 Agent

  - 文件上传与存储服务。
  - SQLite 持久化和 repository 层。
  - 哈希计算、文件类型识别、路径检查。
  - 压缩包解压、安全校验、路径穿越防护。
  - 真正的文件重命名执行器。
  - 审批管理器。
  - 审计日志写入器。
  - 状态机驱动器。
  - 对 Agent 输出做 schema 校验的解析器。

  五、推荐的 LangGraph 工作流
  我建议拆成 5 条 graph，不要做一个超级大 graph。

  1. 课程初始化 Graph

  - 节点 save_roster_files
  - 节点 course_init_agent_extract
  - 节点 validate_roster_json
  - 节点 build_roster_candidates
  - 节点 mark_needs_review_or_confirmed
  - 节点 apply_roster_to_enrollment

  这里真正是 Agent 的只有 course_init_agent_extract。

  2. 作业导入 Graph

  - 节点 scan_submission_root
  - 节点 extract_top_level_entries
  - 节点 submission_import_agent_match
  - 节点 score_match_candidates
  - 节点 persist_submission_candidates
  - 节点 mark_needs_review_or_confirmed

  这里真正是 Agent 的主要是 submission_import_agent_match。

  3. 命名规范 Graph

  - 节点 load_assignment_submissions
  - 节点 naming_policy_agent_plan
  - 节点 detect_naming_exceptions
  - 节点 build_naming_plan
  - 节点 create_approval_task
  - 节点 execute_naming_plan_after_approval
  - 节点 write_audit_events

  这里真正是 Agent 的是 naming_policy_agent_plan 和 detect_naming_exceptions。
  真正执行重命名的不是 Agent。

  4. 评审初始化 Graph

  - 节点 collect_materials
  - 节点 review_material_parser_agent
  - 节点 answer_generator_agent
  - 节点 answer_critic_agent
  - 节点 answer_judge_agent
  - 节点 rubric_finalize
  - 节点 persist_review_prep
  - 节点 wait_user_confirmation

  这是最适合 LangGraph 的一条，因为它天然有循环。

  5. 正式评审 Graph

  - 节点 load_review_prep
  - 节点 select_assets_agent
  - 节点 parse_selected_assets
  - 节点 grading_agent
  - 节点 grading_validator_agent
  - 节点 persist_review_result
  - 节点 mark_manual_review_queue_if_needed

  这里建议并行的是“每份 submission 一条子图”，而不是在一条图里硬并发所有节点。

  六、API 草案
  我按模块给你一版 REST 草案。

  课程

  - POST /courses
    作用：创建课程。
  - GET /courses
    作用：课程列表。
  - GET /courses/{course_id}
    作用：课程详情。
  - PATCH /courses/{course_id}
    作用：修改课程基础信息。
  - POST /courses/{course_id}/archive
    作用：归档课程。

  名单初始化

  - POST /courses/{course_id}/roster-imports
    作用：上传名单文件并创建初始化批次。
  - GET /courses/{course_id}/roster-imports
    作用：查看课程下名单导入历史。
  - GET /roster-imports/{batch_id}
    作用：查看某次导入批次详情。
  - POST /roster-imports/{batch_id}/run
    作用：启动初始化 Agent。
  - GET /roster-imports/{batch_id}/candidates
    作用：查看候选名单行。
  - POST /roster-imports/{batch_id}/confirm
    作用：确认名单候选结果。
  - POST /roster-imports/{batch_id}/apply
    作用：正式写入课程名单。
  - POST /roster-imports/{batch_id}/cancel
    作用：取消本次导入。

  课程名单

  - GET /courses/{course_id}/enrollments
    作用：查看课程名单。
  - PATCH /enrollments/{enrollment_id}
    作用：修正某个课程内学生信息。
  - POST /courses/{course_id}/enrollments/bulk-replace
    作用：大批量名单替换。
    这类操作必须生成审批任务。

  作业定义

  - POST /courses/{course_id}/assignments
    作用：创建第 N 次作业。
  - GET /courses/{course_id}/assignments
    作用：作业列表。
  - GET /assignments/{assignment_id}
    作用：作业详情。
  - PATCH /assignments/{assignment_id}
    作用：修改作业基础信息。

  作业导入

  - POST /assignments/{assignment_id}/submission-imports
    作用：指定作业文件夹，创建导入批次。
  - GET /assignments/{assignment_id}/submission-imports
    作用：查看导入历史。
  - GET /submission-imports/{batch_id}
    作用：查看导入批次详情。
  - POST /submission-imports/{batch_id}/run
    作用：启动导入 Agent。
  - GET /submission-imports/{batch_id}/submissions
    作用：查看识别出的提交及匹配状态。
  - POST /submission-imports/{batch_id}/confirm
    作用：确认匹配结果。
  - POST /submission-imports/{batch_id}/apply
    作用：正式写入提交记录。

  提交与资产

  - GET /assignments/{assignment_id}/submissions
    作用：查看作业提交总表。
  - GET /submissions/{submission_id}
    作用：单份提交详情。
  - GET /submissions/{submission_id}/assets
    作用：查看该提交下文件资产。
  - PATCH /submissions/{submission_id}/match
    作用：人工修正学生归属。
  - PATCH /submission-assets/{asset_id}
    作用：标记忽略/有效。

  命名规范

  - POST /assignments/{assignment_id}/naming-policies
    作用：提交模板或自然语言描述。
  - GET /assignments/{assignment_id}/naming-policies
    作用：查看命名策略版本。
  - POST /assignments/{assignment_id}/naming-plans
    作用：生成命名修正规划。
  - GET /naming-plans/{plan_id}
    作用：查看修正规划与命令预览。
  - POST /naming-plans/{plan_id}/submit-approval
    作用：生成审批任务。
  - POST /naming-plans/{plan_id}/execute
    作用：审批通过后执行。
  - POST /naming-plans/{plan_id}/rollback
    作用：按记录回滚。

  评审初始化

  - POST /assignments/{assignment_id}/review-preps
    作用：上传题目、答案、评分规范材料，创建评审初始化任务。
  - GET /assignments/{assignment_id}/review-preps
    作用：查看历史版本。
  - GET /review-preps/{review_prep_id}
    作用：查看当前评审初始化结果。
  - POST /review-preps/{review_prep_id}/run
    作用：启动评审初始化 Graph。
  - GET /review-preps/{review_prep_id}/questions
    作用：查看拆题结果。
  - PATCH /review-question-items/{item_id}
    作用：人工修正某题内容。
  - POST /review-preps/{review_prep_id}/confirm
    作用：确认本版题目/答案/rubric 成为正式评审输入。

  正式评审

  - POST /assignments/{assignment_id}/review-runs
    作用：创建正式评审任务。
  - GET /assignments/{assignment_id}/review-runs
    作用：查看评审历史。
  - GET /review-runs/{review_run_id}
    作用：查看进度、统计、失败项。
  - POST /review-runs/{review_run_id}/start
    作用：开始并行评审。
  - POST /review-runs/{review_run_id}/retry-failed
    作用：重试失败项。
  - GET /review-runs/{review_run_id}/results
    作用：获取评分结果。
  - PATCH /review-results/{result_id}/manual-review
    作用：人工复核。
  - POST /review-runs/{review_run_id}/publish
    作用：发布最终结果。

  审批

  - GET /approval-tasks
    作用：查看待确认操作。
  - GET /approval-tasks/{approval_task_id}
    作用：查看操作计划详情。
  - POST /approval-tasks/{approval_task_id}/approve
    作用：批准执行。
  - POST /approval-tasks/{approval_task_id}/reject
    作用：拒绝执行。
  - POST /approval-tasks/{approval_task_id}/cancel
    作用：取消审批。

  日志与审计

  - GET /agent-runs
    作用：查看 Agent 运行历史。
  - GET /agent-runs/{agent_run_id}
    作用：查看单次运行详情。
  - GET /agent-runs/{agent_run_id}/tool-calls
    作用：查看工具调用留痕。
  - GET /submissions/{submission_id}/audit-events
    作用：查看某份作业全链路审计。
  - GET /courses/{course_id}/audit-events
    作用：查看课程级审计。
  - GET /objects/{object_type}/{object_id}/logs
    作用：统一日志查询入口。

  七、哪些接口一定要走审批
  下面这些我建议强制生成 approval_task，不能直接执行：

  - 批量重命名。
  - 删除文件。
  - 覆盖已有文件。
  - 批量替换课程名单。
  - 人工批量修正学生归属。
  - 回滚已执行的命名操作。
  - 发布最终评审结果。
  - 对已发布结果做重新覆盖。

  八、日志留痕建议
  你最关心这块，我直接给原则。

  - 不记录“模型私有思维链”。
  - 记录“提示词版本、输入摘要、工具调用、结构化中间结果、重试原因、最终 JSON、错误信息”。
  - 文件操作必须记录 command_preview、执行前后路径、文件哈希变化。
  - 每次 Agent 运行必须可追到 graph_name、agent_name、model_name、prompt_version。
  - 每次人工确认必须记录 谁确认、何时确认、确认了哪些项、拒绝原因是什么。

  九、我对这版蓝图的建议取舍

  - 我建议“提交导入”和“命名修正”先不要允许自动删除，只允许改名和标记忽略。
  - 我建议“评审初始化”必须人工确认后才能进入正式评审，不要自动放行。
  - 我建议“正式评审”先支持整份作业评分，题目级拆分可以保留数据结构，但实现可以分两阶段上。
  - 我建议“资产筛选 Agent”和“评分 Agent”分开，不要合并，不然出了错很难判断是文件选错还是评分错。

  十、我认为最合理的第一阶段后端实现顺序

  1. 先重做数据库模型。
  2. 先做 course + roster_import_batch + course_enrollment。
  3. 再做 assignment + submission_import_batch + submission + submission_asset。
  4. 再做 naming_policy + naming_plan + approval_task。
  5. 再做 review_prep + review_question_item + answer_generation_round。
  6. 最后做 review_run + review_result + agent_run + audit_event。