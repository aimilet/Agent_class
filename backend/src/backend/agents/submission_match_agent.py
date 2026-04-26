from __future__ import annotations

from backend.agents.base import StructuredAgent
from backend.agents.contracts import SubmissionMatchStructuredOutput
from backend.infra.llm import StructuredLlmRequest
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


class SubmissionMatchAgent(StructuredAgent[SubmissionMatchStructuredOutput]):
    name = "submission_match_agent"
    prompt_version = "v2.0.0"
    output_model = SubmissionMatchStructuredOutput

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        entry_manifest = envelope.payload.get("entry_manifest", [])
        enrollments = envelope.payload.get("enrollments", [])
        lines = ["任务：根据作业入口名称和课程名单，把每个提交入口匹配到最可能的学生。"]
        lines.append("提交入口：")
        for entry in entry_manifest:
            lines.append(f"- source_entry_name: {entry['source_entry_name']}")
            lines.append(f"  source_entry_path: {entry['source_entry_path']}")
        lines.append("课程名单：")
        for enrollment in enrollments:
            lines.append(
                f"- public_id: {enrollment['public_id']} | display_student_no: {enrollment.get('display_student_no') or ''} | display_name: {enrollment.get('display_name') or ''}"
            )
        return StructuredLlmRequest(
            system_prompt=(
                "你是作业导入匹配 Agent。\n"
                "职责边界：只判断每个提交入口最可能对应哪个学生，不做数据库写入、不做文件改名。\n"
                "输出要求：每个提交入口必须返回 status=matched|ambiguous|unmatched，并给出最多 3 个候选、置信度和原因。"
            ),
            user_content="\n".join(lines),
            output_model=self.output_model,
            temperature=0.0,
        )

    def build_response(self, result: SubmissionMatchStructuredOutput, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        results = [item.model_dump(mode="json") for item in result.submissions]
        needs_review = any(item["status"] != "matched" for item in results)
        return AgentOutputEnvelope(
            status="succeeded",
            confidence=0.88 if results else 0.0,
            summary=f"已为 {len(results)} 个提交入口生成匹配候选。",
            needs_review=needs_review,
            structured_output={"submissions": results},
            metrics={"input_items": len(envelope.payload.get("entry_manifest", [])), "output_items": len(results)},
        )
