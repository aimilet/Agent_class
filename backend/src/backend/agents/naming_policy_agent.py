from __future__ import annotations

import re

from backend.agents.base import StructuredAgent
from backend.agents.contracts import NamingPolicyStructuredOutput
from backend.infra.llm import StructuredLlmRequest
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")
ALLOWED_PLACEHOLDERS = {"assignment", "class_name", "student_no", "name", "original_stem"}


class NamingPolicyAgent(StructuredAgent[NamingPolicyStructuredOutput]):
    name = "naming_policy_agent"
    prompt_version = "v2.0.0"
    output_model = NamingPolicyStructuredOutput

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        natural_language_rule = envelope.payload.get("natural_language_rule") or ""
        template_text = envelope.payload.get("template_text") or ""
        return StructuredLlmRequest(
            system_prompt=(
                "你是命名规范规划 Agent。\n"
                "职责边界：把自然语言命名规则转换成安全的 Python format 模板，不做实际改名。\n"
                "可用占位符只有：assignment、class_name、student_no、name、original_stem。\n"
                "输出时如果用户规则不完整，也要给出最合理模板，并把风险写到 warnings。"
            ),
            user_content=(
                f"现有模板：{template_text or '无'}\n"
                f"自然语言规则：{natural_language_rule or '无'}\n"
                "请输出标准模板。"
            ),
            output_model=self.output_model,
            temperature=0.0,
        )

    def build_response(self, result: NamingPolicyStructuredOutput, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        placeholders = {item.strip() for item in PLACEHOLDER_RE.findall(result.template_text)}
        warnings = list(result.warnings)
        if not placeholders or not placeholders.issubset(ALLOWED_PLACEHOLDERS):
            result.template_text = "{assignment}_{student_no}_{name}"
            warnings.append("模型返回了非法占位符，已回退到默认安全模板。")
        return AgentOutputEnvelope(
            status="succeeded",
            confidence=0.9,
            summary="已生成规范命名模板。",
            structured_output={
                "template_text": result.template_text,
                "natural_language_rule": result.natural_language_rule,
                "warnings": warnings,
            },
            warnings=warnings,
        )
