from __future__ import annotations

from backend.agents.base import StructuredAgent
from backend.agents.contracts import GradingStructuredOutput
from backend.infra.llm import StructuredLlmRequest, build_file_message_parts
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


class GradingAgent(StructuredAgent[GradingStructuredOutput]):
    name = "grading_agent"
    prompt_version = "v2.0.0"
    output_model = GradingStructuredOutput

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        selected_assets = envelope.payload.get("selected_assets", [])
        content = [
            {
                "type": "text",
                "text": (
                    f"题目与评分基线：\n{envelope.payload.get('reference_text', '')}\n\n"
                    f"分值量程：{int(envelope.payload.get('score_scale', 100))}\n"
                    f"已选文件：{selected_assets}\n\n"
                    "学生作答已作为原始附件提供。请直接读取附件内容评分；"
                    "只有附件无法读取时，才参考后面的本地解析兜底文本。"
                ),
            },
            *build_file_message_parts(selected_assets, path_key="real_path", filename_key="logical_path"),
        ]
        submission_text = envelope.payload.get("submission_text", "")
        if submission_text:
            content.append({"type": "text", "text": f"本地解析兜底文本：\n{submission_text}"})
        return StructuredLlmRequest(
            system_prompt=(
                "你是正式评审评分 Agent。\n"
                "职责边界：只根据题目、参考答案、评分规则和学生作答给出结构化评分结果，不做最终发布。\n"
                "输出要求：total_score 必须在 score_scale 范围内；summary 要写明主要依据；如果有按题评分能力，请填 item_results。"
            ),
            user_content=content,
            output_model=self.output_model,
            temperature=0.0,
        )

    def build_response(self, result: GradingStructuredOutput, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        return AgentOutputEnvelope(
            status="succeeded",
            confidence=result.confidence,
            summary=f"已完成评分，得分 {result.total_score}/{result.score_scale}。",
            needs_review=result.confidence < 0.7,
            structured_output=result.model_dump(mode="json"),
        )
