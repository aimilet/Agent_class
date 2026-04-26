from __future__ import annotations

from backend.agents.base import StructuredAgent
from backend.agents.contracts import AnswerCritiqueStructuredOutput
from backend.infra.llm import StructuredLlmRequest
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


class AnswerCriticAgent(StructuredAgent[AnswerCritiqueStructuredOutput]):
    name = "answer_critic_agent"
    prompt_version = "v2.0.0"
    output_model = AnswerCritiqueStructuredOutput

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        question_text = envelope.payload.get("question_text", "")
        answer_text = envelope.payload.get("reference_answer_full", "")
        return StructuredLlmRequest(
            system_prompt=(
                "你是参考答案纠错 Agent。\n"
                "职责边界：专门挑错、找缺项、找逻辑漏洞，不负责重写完整答案。\n"
                "输出要求：issues 只列真正会影响正确性或评分完整性的点；suggestion 给简洁修正方向。"
            ),
            user_content=f"题目：\n{question_text}\n\n当前答案：\n{answer_text}",
            output_model=self.output_model,
            temperature=0.0,
        )

    def build_response(self, result: AnswerCritiqueStructuredOutput, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        return AgentOutputEnvelope(
            status="succeeded",
            confidence=0.8,
            summary="已完成答案审查。",
            needs_review=bool(result.issues),
            structured_output=result.model_dump(mode="json"),
        )
