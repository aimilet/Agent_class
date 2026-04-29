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
        extracted_visual_assets = envelope.payload.get("extracted_visual_assets", [])
        content = [
            {
                "type": "text",
                "text": (
                    f"题目与评分基线：\n{envelope.payload.get('reference_text', '')}\n\n"
                    f"分值量程：{int(envelope.payload.get('score_scale', 100))}\n"
                    f"原始文件：{selected_assets}\n"
                    f"提取图片数量：{len(extracted_visual_assets)}\n\n"
                    "学生作答会同时提供原始文件、本地提取的正文文本，以及从原始文档中拆出的内嵌图片。"
                    "你必须综合三类材料一起评分，不能只看其中一种。"
                    "如果正文里某道题看起来是空白，但提取图片中存在对应内容，应视为已作答并据此评分。"
                ),
            },
            *build_file_message_parts(selected_assets, path_key="real_path", filename_key="logical_path"),
        ]
        submission_text = envelope.payload.get("submission_text", "")
        if submission_text:
            content.append({"type": "text", "text": f"本地提取的正文文本：\n{submission_text}"})
        if extracted_visual_assets:
            content.append(
                {
                    "type": "text",
                    "text": "以下图片是从原始文档中提取出的内嵌图片，请结合原始文件和正文文本共同判读，不要遗漏图片中的后续题目作答。",
                }
            )
            content.extend(
                build_file_message_parts(
                    extracted_visual_assets,
                    path_key="real_path",
                    filename_key="logical_path",
                    image_limit=int(
                        envelope.payload.get(
                            "vision_max_assets_per_submission",
                            self.settings.vision_max_assets_per_submission,
                        )
                    ),
                )
            )
        return StructuredLlmRequest(
            system_prompt=(
                "你是正式评审评分 Agent。\n"
                "职责边界：只根据题目、参考答案、评分规则和学生作答给出结构化评分结果，不做最终发布。\n"
                "判题要求：必须综合原始文件、正文提取文本、内嵌图片三类证据，不得因为正文空白就忽略图片里的答案。\n"
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
