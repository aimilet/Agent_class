from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.agents import AnswerCriticAgent, AnswerGeneratorAgent, AnswerJudgeAgent, ReviewMaterialParserAgent
from backend.agents.base import AgentExecutor
from backend.core.settings import get_settings
from backend.domain.models import ReviewAnswerGenerationRound, ReviewPrep, ReviewQuestionItem
from backend.graphs.common import compile_graph
from backend.infra.observability import AuditService
from backend.schemas.common import AgentInputEnvelope, AgentRunContext, AgentTaskContext


class ReviewPrepGraphInput(TypedDict):
    review_prep_public_id: str
    assignment_public_id: str
    operator_id: str


class ReviewPrepState(ReviewPrepGraphInput, total=False):
    materials: list[dict[str, Any]]
    question_items: list[dict[str, Any]]
    needs_review: bool


class ReviewPrepGraph:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit_service = AuditService(session)
        self.parser_agent = ReviewMaterialParserAgent()
        self.answer_generator_agent = AnswerGeneratorAgent()
        self.answer_critic_agent = AnswerCriticAgent()
        self.answer_judge_agent = AnswerJudgeAgent()
        self.executor = AgentExecutor(session)
        self.settings = get_settings()
        self.compiled = compile_graph(
            state_schema=ReviewPrepState,
            input_schema=ReviewPrepGraphInput,
            output_schema=ReviewPrepState,
            name="review_prep_graph",
            nodes=[
                ("parse_materials", self.parse_materials),
                ("generate_answers", self.generate_answers),
                ("persist_review_prep", self.persist_review_prep),
            ],
            edges=[
                ("parse_materials", "generate_answers"),
                ("generate_answers", "persist_review_prep"),
            ],
        )

    def invoke(self, *, review_prep_public_id: str, operator_id: str = "system") -> dict[str, Any]:
        review_prep = self.session.scalar(select(ReviewPrep).where(ReviewPrep.public_id == review_prep_public_id))
        state: ReviewPrepGraphInput = {
            "review_prep_public_id": review_prep_public_id,
            "assignment_public_id": review_prep.assignment.public_id,
            "operator_id": operator_id,
        }
        if self.compiled is not None:
            return self.compiled.invoke(state)
        fallback_state: ReviewPrepState = {
            **state,
            "materials": review_prep.source_materials_json,
            "needs_review": False,
        }
        for node in (self.parse_materials, self.generate_answers, self.persist_review_prep):
            fallback_state = node(fallback_state)
        return fallback_state

    def parse_materials(self, state: ReviewPrepState) -> ReviewPrepState:
        review_prep = self.session.scalar(select(ReviewPrep).where(ReviewPrep.public_id == state["review_prep_public_id"]))
        review_prep.status = "material_parsing"
        self.session.flush()
        materials = review_prep.source_materials_json
        envelope = AgentInputEnvelope(
            run_context=AgentRunContext(
                graph_name="review_prep_graph",
                stage_name="review_material_parser_agent",
                run_id=f"review_prep:{review_prep.public_id}",
                assignment_id=state["assignment_public_id"],
                review_prep_id=review_prep.public_id,
                prompt_version=self.parser_agent.prompt_version,
                model_name=self.parser_agent.model_name,
            ),
            task_context=AgentTaskContext(now=datetime.now(), operator_id=state["operator_id"]),
            payload={"materials": materials},
        )
        result = self.executor.run(
            graph_name="review_prep_graph",
            stage_name="review_material_parser_agent",
            agent_name=self.parser_agent.name,
            prompt_version=self.parser_agent.prompt_version,
            model_name=self.parser_agent.model_name,
            envelope=envelope,
            handler=self.parser_agent,
        )
        review_prep.status = "question_structuring"
        self.session.flush()
        return {
            **state,
            "materials": materials,
            "question_items": result.output.structured_output.get("question_items", []),
            "needs_review": result.output.needs_review,
        }

    def generate_answers(self, state: ReviewPrepState) -> ReviewPrepState:
        review_prep = self.session.scalar(select(ReviewPrep).where(ReviewPrep.public_id == state["review_prep_public_id"]))
        max_rounds = max(1, self.settings.max_answer_rounds)
        for question in state["question_items"]:
            reference_short = None
            reference_full = None
            issues: list[str] = []
            for round_no in range(1, max_rounds + 1):
                review_prep.status = "answer_generating"
                self.session.flush()
                generator_output = self.executor.run(
                    graph_name="review_prep_graph",
                    stage_name="answer_generator_agent",
                    agent_name=self.answer_generator_agent.name,
                    prompt_version=self.answer_generator_agent.prompt_version,
                    model_name=self.answer_generator_agent.model_name,
                    envelope=AgentInputEnvelope(
                        run_context=AgentRunContext(
                            graph_name="review_prep_graph",
                            stage_name="answer_generator_agent",
                            run_id=f"review_prep:{review_prep.public_id}:q{question['question_no']}:r{round_no}",
                            assignment_id=state["assignment_public_id"],
                            review_prep_id=review_prep.public_id,
                            prompt_version=self.answer_generator_agent.prompt_version,
                            model_name=self.answer_generator_agent.model_name,
                        ),
                        task_context=AgentTaskContext(now=datetime.now(), operator_id=state["operator_id"]),
                        payload={"question_text": question["question_full_text"], "reference_hint": reference_full or ""},
                    ),
                    handler=self.answer_generator_agent,
                ).output
                reference_short = generator_output.structured_output["reference_answer_short"]
                reference_full = generator_output.structured_output["reference_answer_full"]
                critic_output = self.executor.run(
                    graph_name="review_prep_graph",
                    stage_name="answer_critic_agent",
                    agent_name=self.answer_critic_agent.name,
                    prompt_version=self.answer_critic_agent.prompt_version,
                    model_name=self.answer_critic_agent.model_name,
                    envelope=AgentInputEnvelope(
                        run_context=AgentRunContext(
                            graph_name="review_prep_graph",
                            stage_name="answer_critic_agent",
                            run_id=f"review_prep:{review_prep.public_id}:q{question['question_no']}:r{round_no}",
                            assignment_id=state["assignment_public_id"],
                            review_prep_id=review_prep.public_id,
                            prompt_version=self.answer_critic_agent.prompt_version,
                            model_name=self.answer_critic_agent.model_name,
                        ),
                        task_context=AgentTaskContext(now=datetime.now(), operator_id=state["operator_id"]),
                        payload={"question_text": question["question_full_text"], "reference_answer_full": reference_full},
                    ),
                    handler=self.answer_critic_agent,
                ).output
                issues = critic_output.structured_output.get("issues", [])
                judge_output = self.executor.run(
                    graph_name="review_prep_graph",
                    stage_name="answer_judge_agent",
                    agent_name=self.answer_judge_agent.name,
                    prompt_version=self.answer_judge_agent.prompt_version,
                    model_name=self.answer_judge_agent.model_name,
                    envelope=AgentInputEnvelope(
                        run_context=AgentRunContext(
                            graph_name="review_prep_graph",
                            stage_name="answer_judge_agent",
                            run_id=f"review_prep:{review_prep.public_id}:q{question['question_no']}:r{round_no}",
                            assignment_id=state["assignment_public_id"],
                            review_prep_id=review_prep.public_id,
                            prompt_version=self.answer_judge_agent.prompt_version,
                            model_name=self.answer_judge_agent.model_name,
                        ),
                        task_context=AgentTaskContext(now=datetime.now(), operator_id=state["operator_id"]),
                        payload={
                            "question_text": question["question_full_text"],
                            "reference_answer_full": reference_full,
                            "issues": issues,
                            "round_no": round_no,
                            "max_rounds": max_rounds,
                        },
                    ),
                    handler=self.answer_judge_agent,
                ).output
                question.setdefault("rounds", []).append(
                    {
                        "round_no": round_no,
                        "generator_output": generator_output.structured_output,
                        "critic_feedback": critic_output.structured_output,
                        "judge_result": judge_output.structured_output,
                        "status": judge_output.structured_output["decision"],
                    }
                )
                if judge_output.structured_output["decision"] == "accepted":
                    break
                if judge_output.structured_output["decision"] == "needs_review":
                    state["needs_review"] = True
                    break
            question["reference_answer_short"] = reference_short
            question["reference_answer_full"] = reference_full
            question["rubric_text"] = "参考答案要点完整、结构清晰、结论正确。"
            if issues:
                state["needs_review"] = True
        return {**state}

    def persist_review_prep(self, state: ReviewPrepState) -> ReviewPrepState:
        review_prep = self.session.scalar(select(ReviewPrep).where(ReviewPrep.public_id == state["review_prep_public_id"]))
        self.session.execute(delete(ReviewAnswerGenerationRound).where(ReviewAnswerGenerationRound.review_prep_id == review_prep.id))
        self.session.execute(delete(ReviewQuestionItem).where(ReviewQuestionItem.review_prep_id == review_prep.id))
        self.session.flush()
        review_prep.status = "needs_review" if state["needs_review"] else "confirmed"
        for question in state["question_items"]:
            item = ReviewQuestionItem(
                public_id=ReviewQuestionItem.build_public_id(),
                review_prep_id=review_prep.id,
                question_no=question["question_no"],
                question_full_text=question["question_full_text"],
                reference_answer_short=question["reference_answer_short"],
                reference_answer_full=question["reference_answer_full"],
                rubric_text=question["rubric_text"],
                score_weight=question.get("score_weight", 1.0),
                status="generated",
            )
            self.session.add(item)
            self.session.flush()
            for round_data in question.get("rounds", []):
                self.session.add(
                    ReviewAnswerGenerationRound(
                        public_id=ReviewAnswerGenerationRound.build_public_id(),
                        review_prep_id=review_prep.id,
                        question_item_id=item.id,
                        round_no=round_data["round_no"],
                        generator_output=round_data["generator_output"],
                        critic_feedback=round_data["critic_feedback"],
                        judge_result=round_data["judge_result"],
                        status=round_data["status"],
                    )
                )
        self.audit_service.record(
            event_type="review_prep_generated",
            object_type="review_prep",
            object_public_id=review_prep.public_id,
            payload={"question_count": len(state["question_items"]), "status": review_prep.status},
        )
        self.session.flush()
        return {**state}
