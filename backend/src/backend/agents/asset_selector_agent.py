from __future__ import annotations

from backend.agents.base import StructuredAgent
from backend.agents.contracts import AssetSelectionStructuredOutput
from backend.infra.llm import StructuredLlmRequest
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


class AssetSelectorAgent(StructuredAgent[AssetSelectionStructuredOutput]):
    name = "asset_selector_agent"
    prompt_version = "v2.0.0"
    output_model = AssetSelectionStructuredOutput

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        assets = envelope.payload.get("assets", [])
        lines = [
            "任务：从提交资产清单中挑出真正有评审价值的文件，忽略编译产物、缓存、依赖和无关文件。",
            "资产清单：",
        ]
        for asset in assets:
            lines.append(f"- public_id: {asset.get('public_id') or ''}")
            lines.append(f"  logical_path: {asset['logical_path']}")
            lines.append(f"  real_path: {asset.get('real_path') or ''}")
            lines.append(f"  mime_type: {asset.get('mime_type') or ''}")
            lines.append(f"  size_bytes: {asset.get('size_bytes') or 0}")
        return StructuredLlmRequest(
            system_prompt=(
                "你是评审辅助资产筛选 Agent。\n"
                "职责边界：只筛选有价值文件，不做评分。\n"
                "优先保留源码、文档、报告、截图、图片、PDF、Word、Notebook；忽略依赖目录、构建目录、缓存和明显无关文件。"
            ),
            user_content="\n".join(lines),
            output_model=self.output_model,
            temperature=0.0,
        )

    def build_response(self, result: AssetSelectionStructuredOutput, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        selected = [item.model_dump(mode="json") for item in result.selected_assets]
        ignored = [item.model_dump(mode="json") for item in result.ignored_assets]
        return AgentOutputEnvelope(
            status="succeeded",
            confidence=0.84,
            summary=f"已选出 {len(selected)} 个有效文件。",
            needs_review=not bool(selected),
            structured_output={"selected_assets": selected, "ignored_assets": ignored},
        )
