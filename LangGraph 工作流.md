  核心原则先定死：
  Graph 负责状态流转，Agent 负责不确定性判断，主程序负责执行与留痕。

  一、统一约束

  - 所有 Graph 都只在状态里传“引用”和“结构化结果”，不直接在 state 中塞大文件二进制。
  - 所有 Agent 输入输出都套统一包裹层，便于日志、重试、审计、回放。
  - 所有 Agent 输出必须先过 Pydantic Schema 校验，失败只能重试或转人工，不允许直接落库。
  - 所有文件改名、删除、覆盖、批量修正，都不是 Agent 直接执行，而是先产出 proposed_operations，再转 approval_task。
  - 所有 Agent 都必须输出 confidence、warnings、needs_review 风险信号。
  - 所有 Graph 都必须有 max_rounds 或 max_retries，禁止无限循环。

  统一输入包裹层建议如下：

  {
    "run_context": {
      "graph_name": "review_prep_graph",
      "stage_name": "answer_generator",
      "run_id": "agr_001",
      "course_id": "course_xxx",
      "assignment_id": "asg_xxx",
      "review_prep_id": "rp_xxx",
      "submission_id": null,
      "prompt_version": "v1.0.0",
      "model_name": "gpt-4.1-mini"
    },
    "task_context": {
      "locale": "zh-CN",
      "now": "2026-04-26T10:00:00+08:00",
      "operator_id": "user_xxx"
    },
    "constraints": {
      "must_return_json": true,
      "allow_tool_calls": false,
      "max_output_tokens": 4000,
      "cannot_write_db": true,
      "cannot_execute_filesystem_mutation": true
    },
    "payload": {}
  }

  统一输出包裹层建议如下：

  {
    "status": "succeeded",
    "confidence": 0.93,
    "summary": "已完成名单结构化提取。",
    "warnings": [],
    "errors": [],
    "needs_review": false,
    "structured_output": {},
    "proposed_operations": [],
    "artifact_refs": [],
    "metrics": {
      "input_items": 3,
      "output_items": 58
    }
  }

  二、LangGraph 工作流草案

  1. 课程初始化 Graph：course_init_graph

  1. save_roster_files
  2. build_material_manifest
  3. extract_material_previews
  4. course_init_agent_extract
  5. validate_roster_json
  6. normalize_roster_candidates
  7. detect_roster_conflicts
  8. human_review_gate
  9. apply_roster_batch
  10. write_audit_events

  - Agent 节点：course_init_agent_extract
  - 非 Agent 节点：文件存储、预览提取、Schema 校验、冲突检测、落库、审计
  - 人工确认节点：human_review_gate
  - 条件分支：
      - 高置信且无冲突：直接 apply_roster_batch
      - 低置信或冲突：进入 human_review_gate
      - Schema 不合法：重试 1 次，再失败标记 failed

  Graph state 建议最少包含：

  {
    "course_id": "course_xxx",
    "roster_import_batch_id": "rib_xxx",
    "source_file_refs": ["file_1", "file_2"],
    "material_manifest": [],
    "preview_refs": [],
    "candidate_rows": [],
    "conflicts": [],
    "review_required": false,
    "final_enrollments": []
  }

  2. 作业导入 Graph：submission_import_graph

  1. scan_submission_root
  2. build_entry_manifest
  3. submission_grouping_agent
  4. submission_match_agent
  5. validate_match_output
  6. persist_submission_candidates
  7. human_review_gate
  8. apply_submission_batch
  9. write_audit_events

  - Agent 节点：submission_grouping_agent、submission_match_agent
  - 非 Agent 节点：扫描目录、清单构建、候选落库、状态更新
  - 人工确认节点：匹配歧义时进入 human_review_gate
  - 条件分支：
      - 唯一高置信匹配：直接确认
      - 多候选或低置信：人工确认
      - 根目录为空或结构异常：失败

  Graph state 建议：

  {
    "assignment_id": "asg_xxx",
    "submission_import_batch_id": "sib_xxx",
    "root_path": "/path/to/homework",
    "entry_manifest": [],
    "logical_submission_groups": [],
    "match_candidates": [],
    "review_required": false,
    "submission_records": []
  }

  3. 命名修正规划 Graph：naming_plan_graph

  1. load_assignment_context
  2. load_current_submissions
  3. naming_policy_agent
  4. naming_exception_agent
  5. build_naming_plan
  6. validate_naming_plan
  7. create_approval_task
  8. wait_for_approval
  9. execute_rename_plan
  10. write_audit_events

  - Agent 节点：naming_policy_agent、naming_exception_agent
  - 非 Agent 节点：计划构建、审批创建、等待审批、真正执行改名
  - 人工确认节点：wait_for_approval
  - 条件分支：
      - 审批通过：执行
      - 审批拒绝：标记 rejected
      - 存在覆盖/冲突：默认禁止自动执行

  Graph state 建议：

  {
    "assignment_id": "asg_xxx",
    "naming_policy_input": {
      "template": null,
      "natural_language_rule": "命名改为 第一次作业_学号_姓名"
    },
    "normalized_policy": {},
    "noncompliant_items": [],
    "naming_operations": [],
    "approval_task_id": "apt_xxx",
    "execution_result": null
  }

  4. 评审初始化 Graph：review_prep_graph

  1. save_review_materials
  2. extract_review_material_previews
  3. review_material_parser_agent
  4. validate_question_items
  5. answer_generation_loop_start
  6. answer_generator_agent
  7. answer_critic_agent
  8. answer_judge_agent
  9. check_round_result
  10. rubric_generator_agent
  11. validate_review_prep
  12. persist_review_prep_draft
  13. human_review_gate
  14. mark_review_prep_ready

  - Agent 节点：review_material_parser_agent、answer_generator_agent、answer_critic_agent、answer_judge_agent、
    rubric_generator_agent
  - 非 Agent 节点：材料存储、预览提取、Schema 校验、回合控制、版本落库
  - 人工确认节点：human_review_gate
  - 条件分支：
      - answer_judge_agent 判定 accepted：进入 rubric 生成
      - revise 且未超过轮次：回到 answer_generator_agent
      - 超过最大轮次：进入 human_review_gate

  Graph state 建议：

  {
    "assignment_id": "asg_xxx",
    "review_prep_id": "rp_xxx",
    "material_refs": [],
    "question_items": [],
    "current_question_no": 1,
    "answer_round": 1,
    "answer_drafts": [],
    "critic_feedbacks": [],
    "judge_decisions": [],
    "rubric_items": [],
    "review_required": false
  }

  5. 正式评审父 Graph：review_run_parent_graph

  1. load_review_prep
  2. load_submission_scope
  3. spawn_submission_review_subgraphs
  4. collect_submission_results
  5. aggregate_run_summary
  6. mark_review_run_completed

  - Agent 节点：无
  - 并行点：spawn_submission_review_subgraphs
  - 重点：并行粒度是“每个 submission 一条子图”，不是一份作业内再无限并行

  父图 state 建议：

  {
    "review_run_id": "rr_xxx",
    "assignment_id": "asg_xxx",
    "review_prep_id": "rp_xxx",
    "submission_ids": ["sub_1", "sub_2"],
    "child_run_refs": [],
    "completed_results": [],
    "failed_results": []
  }

  6. 单份作业评审子 Graph：submission_review_graph

  1. load_submission_assets
  2. asset_selector_agent
  3. parse_selected_assets
  4. build_grading_input
  5. grading_agent
  6. grading_validator_agent
  7. manual_review_router
  8. persist_review_result
  9. write_audit_events

  - Agent 节点：asset_selector_agent、grading_agent、grading_validator_agent
  - 非 Agent 节点：文件解析、评分输入组装、落库
  - 条件分支：
      - grading_validator_agent 通过：直接落库为 validated
      - grading_validator_agent 不通过：进入人工复核队列
      - 资产不足或解析失败：标记 failed 或 needs_manual_review

  子图 state 建议：

  {
    "review_run_id": "rr_xxx",
    "submission_id": "sub_xxx",
    "asset_manifest": [],
    "selected_assets": [],
    "ignored_assets": [],
    "parsed_bundle_ref": "pb_xxx",
    "grading_input": {},
    "grading_output": {},
    "validation_output": {},
    "manual_review_required": false
  }

  三、Agent Schema 与提示词职责边界

  下面每个 Agent 我都只写 payload 和 structured_output，默认外层统一使用上面的包裹层。

  1. course_init_agent

  - 用途：从 Excel、PDF、图片名单中抽取课程学生结构化名单
  - 工具权限：无工具，消费上游提供的多模态预览与文本预览
  - 输入 payload

  {
    "course_meta": {
      "course_name": "数据结构",
      "term": "2026春"
    },
    "material_manifest": [
      {
        "file_ref": "file_xxx",
        "filename": "名单.pdf",
        "mime_type": "application/pdf",
        "page_count": 3,
        "preview_ref": "preview_xxx"
      }
    ],
    "output_constraints": {
      "required_fields": ["student_no", "name"],
      "optional_fields": ["source_page", "source_row", "confidence_note"]
    }
  }

  - 输出 structured_output

  {
    "students": [
      {
        "student_no": "20230001",
        "name": "张三",
        "source_file_ref": "file_xxx",
        "source_page": 1,
        "source_row": "R12",
        "raw_fragment": "20230001 张三",
        "confidence": 0.98,
        "notes": []
      }
    ],
    "global_notes": [],
    "needs_review": false
  }

  - 提示词职责边界
  - 只做名单抽取，不做去重，不做课程名单生效，不做数据库写入。
  - 不能猜不存在的学号或姓名。
  - 看不清时必须保留 raw_fragment 并降置信度。
  - 必须只输出 JSON。

  2. submission_grouping_agent

  - 用途：把作业文件夹中的入口归并成逻辑提交单元
  - 工具权限：只读工具
  - 允许工具：list_tree、read_file_head、file_meta
  - 输入 payload

  {
    "assignment_meta": {
      "assignment_id": "asg_xxx",
      "title": "第一次作业"
    },
    "entry_manifest": [
      {
        "entry_path": "/root/张三.zip",
        "entry_type": "file",
        "mime_type": "application/zip",
        "size_bytes": 102400
      }
    ]
  }

  - 输出 structured_output

  {
    "logical_groups": [
      {
        "group_id": "grp_001",
        "entry_paths": ["/root/张三.zip"],
        "group_label": "可能是单个学生提交",
        "confidence": 0.95,
        "reason": "单一压缩包且名称看起来像个人提交"
      }
    ]
  }

  - 提示词职责边界
  - 只做分组，不做学生匹配，不做评审。
  - 不允许执行解压，解压由主程序完成。
  - 不允许修改文件系统。

  3. submission_match_agent

  - 用途：把逻辑提交单元与课程内学生做候选匹配
  - 工具权限：无工具
  - 输入 payload

  {
    "course_roster": [
      {
        "enrollment_id": "enr_001",
        "student_no": "20230001",
        "name": "张三"
      }
    ],
    "logical_groups": [
      {
        "group_id": "grp_001",
        "entry_paths": ["/root/张三.zip"],
        "group_label": "可能是单个学生提交"
      }
    ]
  }

  - 输出 structured_output

  {
    "match_results": [
      {
        "group_id": "grp_001",
        "candidates": [
          {
            "enrollment_id": "enr_001",
            "confidence": 0.97,
            "reason": "文件名命中姓名"
          }
        ],
        "decision": "unique_match",
        "needs_review": false
      }
    ]
  }

  - 提示词职责边界
  - 只输出候选匹配，不做最终确认。
  - 高置信和低置信必须区分。
  - 不能为了“凑结果”强行给出唯一匹配。

  4. naming_policy_agent

  - 用途：把模板或自然语言规范转成稳定命名策略
  - 工具权限：无工具
  - 输入 payload

  {
    "assignment_meta": {
      "seq_no": 1,
      "title": "第一次作业"
    },
    "user_rule": {
      "template": null,
      "natural_language_rule": "命名改为 第一次作业_学号_姓名"
    },
    "allowed_variables": ["assignment_seq", "assignment_title", "student_no", "student_name"]
  }

  - 输出 structured_output

  {
    "normalized_template": "{assignment_title}_{student_no}_{student_name}",
    "variables_used": ["assignment_title", "student_no", "student_name"],
    "separator": "_",
    "policy_notes": [],
    "needs_review": false
  }

  - 提示词职责边界
  - 只做规则归一化，不扫描文件，不执行改名。
  - 不能生成未授权变量。
  - 模板必须可被主程序安全渲染。

  5. naming_exception_agent

  - 用途：识别不规范命名与潜在冲突
  - 工具权限：无工具
  - 输入 payload

  {
    "normalized_template": "{assignment_title}_{student_no}_{student_name}",
    "submissions": [
      {
        "submission_id": "sub_001",
        "current_path": "/root/zs_homework.zip",
        "canonical_context": {
          "assignment_title": "第一次作业",
          "student_no": "20230001",
          "student_name": "张三"
        }
      }
    ]
  }

  - 输出 structured_output

  {
    "noncompliant_items": [
      {
        "submission_id": "sub_001",
        "source_path": "/root/zs_homework.zip",
        "target_filename": "第一次作业_20230001_张三.zip",
        "compliance_status": "rename_required",
        "risk_level": "low",
        "reason": "当前文件名不符合规范模板"
      }
    ]
  }

  - 提示词职责边界
  - 只给出改名建议，不做文件操作。
  - 有路径冲突风险时必须标成 risk_level=high。
  - 不能静默忽略异常项。

  6. review_material_parser_agent

  - 用途：把题目、答案、评分规范材料解析成单题结构
  - 工具权限：无工具
  - 输入 payload

  {
    "material_manifest": [
      {
        "file_ref": "mat_001",
        "role": "question",
        "preview_ref": "preview_q_1"
      },
      {
        "file_ref": "mat_002",
        "role": "answer_optional",
        "preview_ref": "preview_a_1"
      }
    ],
    "parse_goal": {
      "split_into_question_items": true,
      "need_reference_answer": true,
      "need_rubric": true
    }
  }

  - 输出 structured_output

  {
    "question_items": [
      {
        "question_no": 1,
        "question_full_text": "请解释二叉树的先序遍历。",
        "source_refs": ["mat_001#p1"],
        "draft_reference_answer": null,
        "draft_rubric": null,
        "score_weight": 1.0
      }
    ],
    "global_notes": []
  }

  - 提示词职责边界
  - 只做结构化拆解，不做最终答案定稿。
  - 不能把不存在的题目拆出来。
  - 遇到题目边界不清时，必须在 global_notes 说明。

  7. answer_generator_agent

  - 用途：为单题生成参考答案草稿
  - 工具权限：无工具
  - 输入 payload

  {
    "question_item": {
      "question_no": 1,
      "question_full_text": "请解释二叉树的先序遍历。"
    },
    "material_context": {
      "course_name": "数据结构",
      "answer_style": "简洁但准确"
    },
    "round_no": 1
  }

  - 输出 structured_output

  {
    "answer_draft": {
      "short_answer": "先访问根节点，再访问左子树，最后访问右子树。",
      "full_answer": "二叉树的先序遍历是...",
      "key_points": ["根左右", "递归顺序", "适用说明"]
    }
  }

  - 提示词职责边界
  - 只生成答案，不评价自己。
  - 不确定时宁可保守，不要编造超出题目的背景。
  - 输出必须可被后续 critic 精确引用。

  8. answer_critic_agent

  - 用途：指出答案草稿中的遗漏、错误、模糊点
  - 工具权限：无工具
  - 输入 payload

  {
    "question_item": {
      "question_no": 1,
      "question_full_text": "请解释二叉树的先序遍历。"
    },
    "answer_draft": {
      "short_answer": "先访问根节点，再访问左子树，最后访问右子树。",
      "full_answer": "二叉树的先序遍历是..."
    }
  }

  - 输出 structured_output

  {
    "critic_feedback": {
      "verdict": "minor_revision",
      "issues": [
        "答案没有说明遍历顺序记忆方式",
        "缺少递归或实现角度的表述"
      ],
      "must_fix": [],
      "suggested_revisions": [
        "补一句‘顺序可记为根左右’"
      ]
    }
  }

  - 提示词职责边界
  - 只做批评，不重写整份答案。
  - 必须区分 must_fix 和 suggested_revisions。
  - 不能为了挑刺而挑刺。

  9. answer_judge_agent

  - 用途：决定当前答案是否通过，是否继续下一轮
  - 工具权限：无工具
  - 输入 payload

  {
    "question_item": {
      "question_no": 1,
      "question_full_text": "请解释二叉树的先序遍历。"
    },
    "answer_draft": {},
    "critic_feedback": {},
    "round_no": 2,
    "max_rounds": 4
  }

  - 输出 structured_output

  {
    "judge_result": {
      "decision": "accepted",
      "reason": "答案已覆盖核心概念且无关键错误",
      "next_action": "proceed_to_rubric",
      "needs_human_review": false
    }
  }

  - 提示词职责边界
  - 只做通过/修正/转人工的裁决。
  - 不重写答案，不自己补答案。
  - 超过最大轮次时只能转人工，不能继续循环。

  10. rubric_generator_agent

  - 用途：生成或归一化评分规范
  - 工具权限：无工具
  - 输入 payload

  {
    "question_item": {
      "question_no": 1,
      "question_full_text": "请解释二叉树的先序遍历。"
    },
    "final_reference_answer": {},
    "user_rubric_optional": null,
    "score_weight": 10
  }

  - 输出 structured_output

  {
    "rubric": {
      "criteria": [
        {
          "criterion": "能准确说出遍历顺序",
          "max_score": 4
        },
        {
          "criterion": "能简洁解释含义或实现方式",
          "max_score": 3
        },
        {
          "criterion": "表达清晰无关键错误",
          "max_score": 3
        }
      ],
      "deduction_rules": []
    }
  }

  - 提示词职责边界
  - 只生成评分规范，不打分。
  - 总分必须与权重匹配。
  - 评分项要可操作，不能写成空话。

  11. asset_selector_agent

  - 用途：从提交资产里选出真正有价值的文件
  - 工具权限：只读工具
  - 允许工具：list_submission_tree、read_asset_preview、get_parser_summary、open_image_preview
  - 输入 payload

  {
    "submission_meta": {
      "submission_id": "sub_xxx",
      "entry_name": "张三_第一次作业.zip"
    },
    "asset_manifest": [
      {
        "asset_id": "ast_001",
        "logical_path": "src/main.c",
        "mime_type": "text/x-c",
        "size_bytes": 1024,
        "preview_ref": "pv_001"
      },
      {
        "asset_id": "ast_002",
        "logical_path": "build/main.o",
        "mime_type": "application/octet-stream",
        "size_bytes": 8192,
        "preview_ref": null
      }
    ],
    "selection_policy": {
      "prefer_source_files": true,
      "ignore_build_artifacts": true,
      "max_selected_assets": 8
    }
  }

  - 输出 structured_output

  {
    "selected_assets": [
      {
        "asset_id": "ast_001",
        "reason": "源代码文件，可能是主要作答内容",
        "confidence": 0.97
      }
    ],
    "ignored_assets": [
      {
        "asset_id": "ast_002",
        "reason": "编译产物，通常不作为评分依据"
      }
    ],
    "summary": "已选择 1 个高价值文件，忽略 1 个编译产物。"
  }

  - 提示词职责边界
  - 只做“选文件”，不评分。
  - 只能用只读工具，不能解压删除不能改名。
  - 不确定时可以多选，但必须说明理由。

  12. grading_agent

  - 用途：对单份作业按题目和 rubric 打分
  - 工具权限：无工具
  - 输入 payload

  {
    "submission_id": "sub_xxx",
    "question_items": [
      {
        "question_no": 1,
        "question_full_text": "请解释二叉树的先序遍历。",
        "reference_answer_short": "根左右",
        "rubric": {
          "criteria": []
        }
      }
    ],
    "selected_assets": [
      {
        "asset_id": "ast_001",
        "parsed_text": "先序遍历就是先访问根..."
      }
    ],
    "grading_policy": {
      "score_scale": 100,
      "must_return_per_question_reason": true
    }
  }

  - 输出 structured_output

  {
    "total_score": 86,
    "decision": "pass",
    "overall_summary": "核心概念基本正确，但实现说明略简略。",
    "item_results": [
      {
        "question_no": 1,
        "score": 8.6,
        "reason": "说对了根左右顺序，但没有展开实现细节。",
        "evidence_refs": ["ast_001#L1-L3"]
      }
    ],
    "confidence": 0.88
  }

  - 提示词职责边界
  - 只评分，不选择文件，不修改 rubric。
  - 分数和理由必须一致。
  - 证据引用必须尽量可追溯。

  13. grading_validator_agent

  - 用途：检查评分结果是否自洽、是否需要人工复核
  - 工具权限：无工具
  - 输入 payload

  {
    "grading_output": {},
    "question_items": [],
    "selected_assets_summary": [],
    "validation_policy": {
      "check_score_reason_consistency": true,
      "check_missing_question": true,
      "manual_review_threshold": 0.6
    }
  }

  - 输出 structured_output

  {
    "validation_result": {
      "verdict": "needs_manual_review",
      "issues": [
        "第 1 题给分较高，但理由偏弱",
        "总评结论与单题理由存在轻微不一致"
      ],
      "recommended_action": "queue_manual_review"
    }
  }

  - 提示词职责边界
  - 只校验，不重新评分。
  - 不能擅自改分。
  - 发现明显不一致时必须转人工复核，而不是自己修补。

  四、运行规范、重试策略与人工确认节点

  统一工具权限分级

  - no_tools
    适用：course_init_agent、submission_match_agent、naming_policy_agent、review_material_parser_agent、grading_agent。
  - read_only_tools
    适用：submission_grouping_agent、asset_selector_agent。
  - execute_tools
    不对 Agent 开放。
    真正执行改名、移动文件、写数据库的，是主程序中的受控执行器节点。

  统一重试策略

  - Schema 解析失败：最多重试 1 次。
  - 模型返回空结果：最多重试 1 次。
  - 工具调用失败：记录 tool_call_log，再由 Graph 决定是否重试。
  - Answer loop：默认最多 4 轮。
  - Grading validator 不通过：不自动重试评分，直接转人工复核更稳。

  统一人工确认节点

  - 名单导入低置信或冲突。
  - 提交导入多候选匹配。
  - 命名计划执行前。
  - 评审初始化确认前。
  - 正式评审结果被 validator 判为 needs_manual_review。
  - 发布最终成绩前。

  统一日志留痕

  - 每个 Graph 节点写 audit_event。
  - 每个 Agent 调用写 agent_run。
  - 每次工具调用写 tool_call_log。
  - 每次审批写 approval_task 和 approval_item。
  - 每次文件改动写“执行前路径、执行后路径、命令预览、文件哈希前后值”。

  统一提示词规则

  - 必须要求“只输出 JSON”。
  - 必须写清楚可用字段、不可用字段。
  - 必须写清楚“不确定时怎么表达”。
  - 必须写清楚“不能做的事”。
  - 必须给出失败时的合法返回格式，而不是让模型自由报错。

  我建议第一阶段先实现的 Agent

  - course_init_agent
  - submission_match_agent
  - naming_policy_agent
  - review_material_parser_agent
  - answer_generator_agent
  - answer_critic_agent
  - answer_judge_agent
  - asset_selector_agent
  - grading_agent
  - grading_validator_agent

  submission_grouping_agent 和 naming_exception_agent 可以放第二阶段，因为第一阶段先用启发式规则替代也能跑通。

  简短总结：
  这份设计里，LangGraph 主要承载的是“状态机和回合控制”，而不是把所有事情都交给大模型。真正应当做成 Agent 的，只有那些需
  要多模态理解、语义匹配、答案生成、评分判断的节点；真正会改文件、改数据库、生成审批、写审计的节点，都必须留在主程序里。