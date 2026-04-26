from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from backend.core.settings import Settings
from backend.services.document_parser import DocumentParser
from backend.services.helpers import filename_tokens, normalize_name, normalize_student_no
from backend.services.student_import import import_students_from_file


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class MockStructuredLlm:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.parser = DocumentParser()

    def invoke(self, request) -> StructuredModel:
        name = request.output_model.__name__
        method = getattr(self, f"_mock_{name}", None)
        if method is None:
            return request.output_model.model_validate({})
        payload = self._flatten_user_content(request.user_content)
        return request.output_model.model_validate(method(payload))

    def _flatten_user_content(self, content: str | list[dict[str, Any]]) -> str:
        if isinstance(content, str):
            return content
        texts: list[str] = []
        for item in content:
            if item.get("type") == "text":
                texts.append(str(item.get("text", "")))
        return "\n".join(texts)

    def _extract_paths(self, text: str) -> list[Path]:
        pattern = re.compile(r"路径：([^\n]+)")
        return [Path(match.group(1).strip()) for match in pattern.finditer(text)]

    def _mock_CourseInitStructuredOutput(self, payload: str) -> dict[str, Any]:
        students: list[dict[str, Any]] = []
        for path in self._extract_paths(payload):
            try:
                result = import_students_from_file(path, parse_mode="auto")
            except Exception:
                continue
            for index, student in enumerate(result.students, start=1):
                students.append(
                    {
                        "student_no": student.student_no,
                        "name": student.name,
                        "source_file": path.name,
                        "page_no": None,
                        "row_ref": f"row-{index}",
                        "raw_fragment": f"{student.student_no or ''} {student.name}".strip(),
                        "confidence": 0.96 if student.student_no else 0.82,
                        "notes": [],
                    }
                )
        return {"students": students, "global_notes": []}

    def _mock_SubmissionMatchStructuredOutput(self, payload: str) -> dict[str, Any]:
        entry_pattern = re.compile(r"source_entry_name:\s*(.+)")
        enrollment_pattern = re.compile(
            r"public_id:\s*(?P<public_id>\S+)\s*\|\s*display_student_no:\s*(?P<student_no>.*?)\s*\|\s*display_name:\s*(?P<name>.+)"
        )
        entries = [match.group(1).strip() for match in entry_pattern.finditer(payload)]
        enrollments = [
            {
                "public_id": match.group("public_id").strip(),
                "student_no": match.group("student_no").strip() or None,
                "name": match.group("name").strip(),
            }
            for match in enrollment_pattern.finditer(payload)
        ]
        submissions: list[dict[str, Any]] = []
        for entry in entries:
            candidates: list[dict[str, Any]] = []
            for enrollment in enrollments:
                confidence = 0.0
                if enrollment["student_no"] and enrollment["student_no"] in entry:
                    confidence += 0.7
                if normalize_name(enrollment["name"]) in normalize_name(entry):
                    confidence += 0.3
                if confidence:
                    candidates.append(
                        {
                            "enrollment_public_id": enrollment["public_id"],
                            "confidence": min(confidence, 0.99),
                            "reason": "mock 匹配命中文件名",
                            "rank_order": len(candidates) + 1,
                        }
                    )
            submissions.append(
                {
                    "source_entry_name": entry,
                    "source_entry_path": entry,
                    "matched_by": "mock_llm",
                    "match_confidence": candidates[0]["confidence"] if candidates else None,
                    "match_reason": candidates[0]["reason"] if candidates else None,
                    "status": "matched" if candidates else "unmatched",
                    "canonical_name": entry,
                    "match_candidates": candidates[:3],
                }
            )
        return {"submissions": submissions}

    def _mock_NamingPolicyStructuredOutput(self, payload: str) -> dict[str, Any]:
        template = "{assignment}_{student_no}_{name}" if "学号" in payload and "姓名" in payload else "{assignment}_{name}"
        return {"template_text": template, "natural_language_rule": None, "warnings": []}

    def _mock_ReviewMaterialParseStructuredOutput(self, payload: str) -> dict[str, Any]:
        texts: list[str] = []
        for path in self._extract_paths(payload):
            try:
                texts.append(self.parser.parse(path).text.strip())
            except Exception:
                continue
        merged = "\n\n".join(texts).strip() or "请回答题目。"
        return {
            "question_items": [
                {
                    "question_no": 1,
                    "question_full_text": merged,
                    "reference_answer_short": None,
                    "reference_answer_full": None,
                    "rubric_text": None,
                    "score_weight": 1.0,
                    "notes": [],
                }
            ]
        }

    def _mock_AnswerGenerationStructuredOutput(self, payload: str) -> dict[str, Any]:
        return {
            "reference_answer_short": "围绕核心概念、关键步骤和最终结论作答。",
            "reference_answer_full": payload[:800] or "围绕核心概念、关键步骤和最终结论作答。",
        }

    def _mock_AnswerCritiqueStructuredOutput(self, payload: str) -> dict[str, Any]:
        issues = [] if len(payload) > 40 else ["答案偏短，建议补充关键步骤。"]
        return {"issues": issues, "suggestion": "补充关键步骤与结论。"}

    def _mock_AnswerJudgeStructuredOutput(self, payload: str) -> dict[str, Any]:
        decision = "needs_review" if "偏短" in payload else "accepted"
        return {"decision": decision, "accepted": decision == "accepted", "issues": []}

    def _mock_AssetSelectionStructuredOutput(self, payload: str) -> dict[str, Any]:
        selected_assets: list[dict[str, Any]] = []
        ignored_assets: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in payload.splitlines():
            stripped = line.strip()
            if stripped.startswith("- public_id:"):
                current = {"public_id": stripped.split(":", 1)[1].strip()}
            elif stripped.startswith("logical_path:"):
                current["logical_path"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("real_path:"):
                current["real_path"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("mime_type:"):
                current["mime_type"] = stripped.split(":", 1)[1].strip() or None
            elif stripped.startswith("size_bytes:"):
                current["size_bytes"] = int(stripped.split(":", 1)[1].strip() or 0)
                suffix = Path(current.get("logical_path", "")).suffix.lower()
                if suffix in {".py", ".ipynb", ".txt", ".md", ".pdf", ".docx", ".png", ".jpg", ".jpeg"}:
                    selected_assets.append({**current, "reason": "mock 选中可评审文件"})
                else:
                    ignored_assets.append({**current, "reason": "mock 忽略非关键文件"})
                current = {}
        return {"selected_assets": selected_assets, "ignored_assets": ignored_assets}

    def _mock_GradingStructuredOutput(self, payload: str) -> dict[str, Any]:
        score = 78.0 if payload.strip() else 0.0
        return {
            "total_score": score,
            "score_scale": self.settings.default_review_scale,
            "summary": "mock 评分完成。",
            "decision": "pass" if score >= 60 else "needs_followup",
            "confidence": 0.76,
            "item_results": [],
        }

    def _mock_GradingValidationStructuredOutput(self, payload: str) -> dict[str, Any]:
        return {"status": "validated", "errors": []}
