from __future__ import annotations

from backend.agents.base import StructuredAgent
from backend.agents.contracts import AnswerJudgeStructuredOutput
from backend.infra.llm import StructuredLlmRequest
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


class AnswerJudgeAgent(StructuredAgent[AnswerJudgeStructuredOutput]):
    name = "answer_judge_agent"
    prompt_version = "v2.0.0"
    output_model = AnswerJudgeStructuredOutput

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        question_text = envelope.payload.get("question_text", "")
        answer_text = envelope.payload.get("reference_answer_full", "")
        issues = envelope.payload.get("issues", [])
        round_no = envelope.payload.get("round_no", 1)
        max_rounds = envelope.payload.get("max_rounds", 3)
        return StructuredLlmRequest(
            system_prompt=(
                "你是参考答案裁决 Agent。\n"
                "职责边界：根据当前答案和审查意见，只判断 accepted / revise / needs_review。\n"
                "判定规则：无关键问题可 accepted；有问题但还有轮次可 revise；问题较重且已到最大轮次则 needs_review。"
            ),
            user_content=(
                f"当前轮次：{round_no}/{max_rounds}\n"
                f"题目：\n{question_text}\n\n"
                f"当前答案：\n{answer_text}\n\n"
                f"问题列表：\n" + ("\n".join(f"- {item}" for item in issues) if issues else "无")
            ),
            output_model=self.output_model,
            temperature=0.0,
        )

    def build_response(self, result: AnswerJudgeStructuredOutput, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        return AgentOutputEnvelope(
            status="succeeded",
            confidence=0.83,
            summary=f"答案判定结果：{result.decision}",
            needs_review=result.decision == "needs_review",
            structured_output=result.model_dump(mode="json"),
        )
