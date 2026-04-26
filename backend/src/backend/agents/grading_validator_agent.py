from __future__ import annotations

from backend.agents.base import StructuredAgent
from backend.agents.contracts import GradingValidationStructuredOutput
from backend.infra.llm import StructuredLlmRequest
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


class GradingValidatorAgent(StructuredAgent[GradingValidationStructuredOutput]):
    name = "grading_validator_agent"
    prompt_version = "v2.0.0"
    output_model = GradingValidationStructuredOutput

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        return StructuredLlmRequest(
            system_prompt=(
                "你是评分校验 Agent。\n"
                "职责边界：检查评分输出是否自洽，不重新评分。\n"
                "如果分数越界、理由缺失、按题得分与总分明显矛盾，返回 needs_manual_review。"
            ),
            user_content=str(envelope.payload),
            output_model=self.output_model,
            temperature=0.0,
        )

    def build_response(self, result: GradingValidationStructuredOutput, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        return AgentOutputEnvelope(
            status="succeeded",
            confidence=0.9,
            summary=f"评分校验结果：{result.status}",
            needs_review=result.status != "validated",
            warnings=result.errors,
            structured_output=result.model_dump(mode="json"),
        )
