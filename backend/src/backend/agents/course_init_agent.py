from __future__ import annotations

from backend.agents.base import StructuredAgent
from backend.agents.contracts import CourseInitStructuredOutput
from backend.infra.llm import StructuredLlmRequest, build_material_message_parts
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


class CourseInitAgent(StructuredAgent[CourseInitStructuredOutput]):
    name = "course_init_agent"
    prompt_version = "v2.0.0"
    output_model = CourseInitStructuredOutput

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        course_meta = envelope.payload.get("course_meta", {})
        material_manifest = envelope.payload.get("material_manifest", [])
        user_parts = [
            {
                "type": "text",
                "text": (
                    f"课程名称：{course_meta.get('course_name', '')}\n"
                    f"学期：{course_meta.get('term', '')}\n"
                    f"班级：{course_meta.get('class_label', '')}\n"
                    "任务：从这些名单材料中抽取学生名单。只抽取你确信存在的学号和姓名。"
                ),
            },
            *build_material_message_parts(material_manifest, text_limit=10000, image_limit=6),
        ]
        return StructuredLlmRequest(
            system_prompt=(
                "你是课程初始化名单抽取 Agent。\n"
                "职责边界：只做名单抽取，不做去重、不做数据库写入、不做课程名单生效。\n"
                "输出要求：识别材料中的学生条目，返回 student_no 和 name；看不清时降低 confidence，并把证据写到 raw_fragment / notes；禁止编造不存在的学号或姓名。"
            ),
            user_content=user_parts,
            output_model=self.output_model,
            temperature=0.0,
        )

    def build_response(self, result: CourseInitStructuredOutput, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        warnings = list(result.global_notes)
        students = [item.model_dump(mode="json") for item in result.students]
        return AgentOutputEnvelope(
            status="succeeded",
            confidence=0.95 if students else 0.2,
            summary=f"已提取 {len(students)} 条名单候选。",
            warnings=warnings,
            needs_review=any(student["confidence"] < 0.9 for student in students) or not students,
            structured_output={"students": students, "global_notes": warnings},
            metrics={"input_items": len(envelope.payload.get('material_manifest', [])), "output_items": len(students)},
        )
