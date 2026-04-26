from __future__ import annotations

from backend.agents.base import StructuredAgent
from backend.agents.contracts import ReviewMaterialParseStructuredOutput
from backend.infra.llm import StructuredLlmRequest, build_material_message_parts
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


class ReviewMaterialParserAgent(StructuredAgent[ReviewMaterialParseStructuredOutput]):
    name = "review_material_parser_agent"
    prompt_version = "v2.0.0"
    output_model = ReviewMaterialParseStructuredOutput

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        materials = envelope.payload.get("materials", [])
        return StructuredLlmRequest(
            system_prompt=(
                "你是评审初始化材料解析 Agent。\n"
                "职责边界：只负责从题目、答案、评分材料中拆出单题结构，不负责最终答案定稿。\n"
                "输出要求：按 question_no 顺序返回 question_items；每题保留完整题干；如果材料中已有答案线索或 rubric 线索，可以先填入草稿，否则留空。"
            ),
            user_content=[
                {"type": "text", "text": "任务：解析这些评审材料，拆出可供后续答案生成和评分使用的单题结构。"},
                *build_material_message_parts(materials, text_limit=12000, image_limit=8),
            ],
            output_model=self.output_model,
            temperature=0.0,
        )

    def build_response(self, result: ReviewMaterialParseStructuredOutput, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        question_items = [item.model_dump(mode="json") for item in result.question_items]
        return AgentOutputEnvelope(
            status="succeeded",
            confidence=0.86,
            summary=f"已拆分出 {len(question_items)} 道题。",
            needs_review=len(question_items) == 1,
            structured_output={"question_items": question_items},
            metrics={"input_items": len(envelope.payload.get("materials", [])), "output_items": len(question_items)},
        )
