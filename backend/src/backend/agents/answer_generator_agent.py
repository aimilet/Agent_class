from __future__ import annotations

from backend.agents.base import StructuredAgent
from backend.agents.contracts import AnswerGenerationStructuredOutput
from backend.infra.llm import StructuredLlmRequest
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


class AnswerGeneratorAgent(StructuredAgent[AnswerGenerationStructuredOutput]):
    name = "answer_generator_agent"
    prompt_version = "v2.0.0"
    output_model = AnswerGenerationStructuredOutput

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        question_text = envelope.payload.get("question_text", "")
        reference_hint = envelope.payload.get("reference_hint", "")
        return StructuredLlmRequest(
            system_prompt=(
                "你是参考答案生成 Agent。\n"
                "职责边界：只为单题生成参考答案草稿，不做最终通过判定。\n"
                "输出要求：reference_answer_short 是简洁版本，reference_answer_full 是完整版本；要尽量正确、完整、可评分。"
            ),
            user_content=(
                f"题目：\n{question_text}\n\n"
                f"已有线索：\n{reference_hint or '无'}\n\n"
                "请生成该题参考答案。"
            ),
            output_model=self.output_model,
            temperature=0.2,
        )

    def build_response(self, result: AnswerGenerationStructuredOutput, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        return AgentOutputEnvelope(
            status="succeeded",
            confidence=0.74,
            summary="已生成参考答案草稿。",
            needs_review=False,
            structured_output=result.model_dump(mode="json"),
        )
