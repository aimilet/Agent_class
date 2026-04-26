from __future__ import annotations

import re
from typing import Any, Protocol, Sequence, TypedDict

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from backend.config import Settings, get_settings
from backend.services.document_parser import VisualAsset
from backend.services.llm_utils import bytes_to_data_url, clamp_score, extract_json, stringify_content


TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+")


def tokenize_text(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())

class AnswerAgent(Protocol):
    def answer(self, question: str, rubric: str | None = None) -> str: ...


class ReviewerAgent(Protocol):
    def review(
        self,
        *,
        question: str,
        rubric: str | None,
        reference_answer: str,
        submission_text: str,
        parser_notes: Sequence[str],
        visual_assets: Sequence[VisualAsset] | None = None,
    ) -> dict[str, Any]: ...


class HeuristicAnswerAgent:
    """未配置大模型时的兜底参考答案生成。"""

    def answer(self, question: str, rubric: str | None = None) -> str:
        keywords = list(dict.fromkeys(tokenize_text(question)))[:8]
        keyword_text = "、".join(keywords) or "围绕题目核心概念作答"
        rubric_text = rubric.strip() if rubric else "概念完整、步骤清晰、结论正确"
        return (
            "自动生成参考答案（演示模式）\n"
            f"题目：{question.strip()[:300]}\n"
            f"评分关注：{rubric_text}\n"
            f"建议覆盖要点：{keyword_text}"
        )


class HeuristicReviewerAgent:
    """基于关键词覆盖率的本地评分基线。"""

    def review(
        self,
        *,
        question: str,
        rubric: str | None,
        reference_answer: str,
        submission_text: str,
        parser_notes: Sequence[str],
        visual_assets: Sequence[VisualAsset] | None = None,
    ) -> dict[str, Any]:
        cleaned_submission = submission_text.strip()
        if not cleaned_submission:
            return {
                "score": 0.0,
                "summary": "未识别到可审阅的正文内容。",
                "strengths": [],
                "issues": ["请检查文件是否为空，或确认 OCR / 文档解析是否成功。", *parser_notes],
                "matched_keywords": [],
                "decision": "needs_retry",
                "review_mode": "text_heuristic",
            }

        reference_tokens = [token for token in tokenize_text(reference_answer) if len(token) >= 2]
        submission_tokens = set(tokenize_text(cleaned_submission))

        unique_reference = list(dict.fromkeys(reference_tokens))
        matched = [token for token in unique_reference if token in submission_tokens]
        missing = [token for token in unique_reference if token not in submission_tokens][:8]

        overlap_ratio = len(matched) / max(len(unique_reference), 1)
        length_ratio = min(len(cleaned_submission) / max(len(reference_answer), 1), 1.0)
        score = round(min(100.0, overlap_ratio * 80 + length_ratio * 20), 2)

        if score >= 85:
            summary = "作答覆盖了大部分参考要点，整体完成度较好。"
            decision = "pass"
        elif score >= 60:
            summary = "作答涉及部分关键点，但仍有明显缺口。"
            decision = "revise"
        else:
            summary = "作答与参考答案重合较少，建议重点补充核心概念和论证过程。"
            decision = "needs_revision"

        strengths = []
        if matched:
            strengths.append(f"已覆盖关键词：{'、'.join(matched[:8])}")
        if len(cleaned_submission) >= 120:
            strengths.append("作答篇幅达到基本说明要求")

        issues = []
        if missing:
            issues.append(f"缺失关键词：{'、'.join(missing)}")
        if parser_notes:
            issues.extend(parser_notes)
        if rubric:
            issues.append(f"评分规则提示：{rubric}")

        return {
            "score": clamp_score(score),
            "summary": summary,
            "strengths": strengths,
            "issues": issues,
            "matched_keywords": matched[:12],
            "decision": decision,
            "review_mode": "text_heuristic",
        }


class OpenAICompatibleAnswerAgent:
    def __init__(self, settings: Settings, fallback: AnswerAgent) -> None:
        self.fallback = fallback
        self.client = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.2,
        )

    def answer(self, question: str, rubric: str | None = None) -> str:
        prompt = (
            "你是助教参考答案生成器。请直接输出一份高质量、结构化的参考答案，"
            "不要输出额外寒暄。\n\n"
            f"题目：\n{question}\n\n"
            f"评分关注：\n{rubric or '概念完整、步骤清晰、结论正确'}"
        )
        try:
            response = self.client.invoke(prompt)
            return stringify_content(response.content).strip()
        except Exception:
            return self.fallback.answer(question, rubric)


class OpenAICompatibleReviewerAgent:
    def __init__(self, settings: Settings, fallback: ReviewerAgent) -> None:
        self.fallback = fallback
        self.max_vision_assets = settings.vision_max_assets_per_submission
        self.client = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0,
        )

    def review(
        self,
        *,
        question: str,
        rubric: str | None,
        reference_answer: str,
        submission_text: str,
        parser_notes: Sequence[str],
        visual_assets: Sequence[VisualAsset] | None = None,
    ) -> dict[str, Any]:
        if visual_assets:
            prompt = (
                "你是助教视觉审阅 Agent。请直接根据题目、参考答案、评分规则和学生作答图片进行视觉评分。"
                "不要假设 OCR 文本一定完整，以图像内容为准。只返回 JSON。\n"
                'JSON 格式：{"score": 0-100, "summary": "...", "strengths": ["..."], '
                '"issues": ["..."], "matched_keywords": ["..."], "decision": "pass|revise|needs_revision"}\n\n'
                f"题目：\n{question}\n\n"
                f"评分规则：\n{rubric or '概念完整、步骤清晰、结论正确'}\n\n"
                f"参考答案：\n{reference_answer[:12000]}\n\n"
                f"本地解析备注：\n{chr(10).join(parser_notes) or '无'}\n\n"
                f"本地 OCR 摘要（仅作参考，可忽略错误）：\n{submission_text[:6000] or '无'}"
            )
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for asset in list(visual_assets)[: self.max_vision_assets]:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": bytes_to_data_url(asset.data, asset.mime_type),
                        },
                    }
                )
            request_payload: Any = [HumanMessage(content=content)]
            review_mode = "vision_llm"
        else:
            prompt = (
                "你是助教审阅 Agent。请根据题目、参考答案、学生作答与解析备注进行评分，"
                "并且只返回 JSON。\n"
                'JSON 格式：{"score": 0-100, "summary": "...", "strengths": ["..."], '
                '"issues": ["..."], "matched_keywords": ["..."], "decision": "pass|revise|needs_revision"}\n\n'
                f"题目：\n{question}\n\n"
                f"评分规则：\n{rubric or '概念完整、步骤清晰、结论正确'}\n\n"
                f"参考答案：\n{reference_answer[:12000]}\n\n"
                f"学生作答：\n{submission_text[:12000]}\n\n"
                f"解析备注：\n{chr(10).join(parser_notes) or '无'}"
            )
            request_payload = prompt
            review_mode = "text_llm"
        try:
            response = self.client.invoke(request_payload)
            payload = extract_json(stringify_content(response.content))
            payload.setdefault("strengths", [])
            payload.setdefault("issues", [])
            payload.setdefault("matched_keywords", [])
            payload.setdefault("decision", "revise")
            payload["score"] = clamp_score(payload.get("score", 0))
            payload["review_mode"] = review_mode
            return payload
        except Exception:
            return self.fallback.review(
                question=question,
                rubric=rubric,
                reference_answer=reference_answer,
                submission_text=submission_text,
                parser_notes=parser_notes,
                visual_assets=visual_assets,
            )


class ReviewState(TypedDict, total=False):
    question: str
    rubric: str | None
    reference_answer: str | None
    submission_text: str
    parser_notes: list[str]
    visual_assets: list[VisualAsset]
    review_mode: str
    resolved_reference_answer: str
    review_result: dict[str, Any]


class ReviewWorkflow:
    """LangGraph 审阅工作流。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        heuristic_answer = HeuristicAnswerAgent()
        heuristic_reviewer = HeuristicReviewerAgent()

        if self.settings.llm_enabled:
            self.answer_agent: AnswerAgent = OpenAICompatibleAnswerAgent(self.settings, heuristic_answer)
            self.reviewer_agent: ReviewerAgent = OpenAICompatibleReviewerAgent(self.settings, heuristic_reviewer)
        else:
            self.answer_agent = heuristic_answer
            self.reviewer_agent = heuristic_reviewer

        graph = StateGraph(ReviewState)
        graph.add_node("prepare_reference", self._prepare_reference)
        graph.add_node("review_submission", self._review_submission)
        graph.add_edge(START, "prepare_reference")
        graph.add_edge("prepare_reference", "review_submission")
        graph.add_edge("review_submission", END)
        self.graph = graph.compile()

    def resolve_reference_answer(self, question: str, rubric: str | None, reference_answer: str | None) -> str:
        if reference_answer and reference_answer.strip():
            return reference_answer.strip()
        return self.answer_agent.answer(question, rubric)

    def _prepare_reference(self, state: ReviewState) -> dict[str, Any]:
        return {
            "resolved_reference_answer": self.resolve_reference_answer(
                state["question"],
                state.get("rubric"),
                state.get("reference_answer"),
            )
        }

    def _review_submission(self, state: ReviewState) -> dict[str, Any]:
        return {
            "review_result": self.reviewer_agent.review(
                question=state["question"],
                rubric=state.get("rubric"),
                reference_answer=state["resolved_reference_answer"],
                submission_text=state["submission_text"],
                parser_notes=state.get("parser_notes", []),
                visual_assets=state.get("visual_assets") if state.get("review_mode") == "vision" else None,
            )
        }

    def run(
        self,
        *,
        question: str,
        rubric: str | None,
        reference_answer: str | None,
        submission_text: str,
        parser_notes: list[str],
        review_mode: str = "text",
        visual_assets: list[VisualAsset] | None = None,
    ) -> dict[str, Any]:
        result = self.graph.invoke(
            {
                "question": question,
                "rubric": rubric,
                "reference_answer": reference_answer,
                "submission_text": submission_text,
                "parser_notes": parser_notes,
                "review_mode": review_mode,
                "visual_assets": visual_assets or [],
            }
        )
        payload = dict(result["review_result"])
        payload["reference_answer"] = result["resolved_reference_answer"]
        return payload
