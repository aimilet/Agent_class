from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin


class ReviewPrep(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "review_prep"
    public_id_prefix = "rp"

    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignment.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)
    source_materials_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assignment: Mapped["Assignment"] = relationship(foreign_keys=[assignment_id])
    question_items: Mapped[list["ReviewQuestionItem"]] = relationship(
        back_populates="review_prep",
        cascade="all, delete-orphan",
    )
    answer_rounds: Mapped[list["ReviewAnswerGenerationRound"]] = relationship(
        back_populates="review_prep",
        cascade="all, delete-orphan",
    )
    review_runs: Mapped[list["ReviewRun"]] = relationship(back_populates="review_prep")


class ReviewQuestionItem(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "review_question_item"
    __table_args__ = (UniqueConstraint("review_prep_id", "question_no", name="uq_review_question_item_prep_question"),)
    public_id_prefix = "rqi"

    review_prep_id: Mapped[int] = mapped_column(ForeignKey("review_prep.id"), nullable=False, index=True)
    question_no: Mapped[int] = mapped_column(Integer, nullable=False)
    question_full_text: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer_short: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_answer_full: Mapped[str | None] = mapped_column(Text, nullable=True)
    rubric_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)

    review_prep: Mapped[ReviewPrep] = relationship(back_populates="question_items")
    answer_rounds: Mapped[list["ReviewAnswerGenerationRound"]] = relationship(back_populates="question_item")
    item_results: Mapped[list["ReviewItemResult"]] = relationship(back_populates="question_item")


class ReviewAnswerGenerationRound(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "review_answer_generation_round"
    public_id_prefix = "ragr"

    review_prep_id: Mapped[int] = mapped_column(ForeignKey("review_prep.id"), nullable=False, index=True)
    question_item_id: Mapped[int] = mapped_column(ForeignKey("review_question_item.id"), nullable=False, index=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    generator_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    critic_feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    judge_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated", index=True)

    review_prep: Mapped[ReviewPrep] = relationship(back_populates="answer_rounds")
    question_item: Mapped[ReviewQuestionItem] = relationship(back_populates="answer_rounds")


class ReviewRun(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "review_run"
    public_id_prefix = "rr"

    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignment.id"), nullable=False, index=True)
    review_prep_id: Mapped[int] = mapped_column(ForeignKey("review_prep.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    parallelism: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    assignment: Mapped["Assignment"] = relationship(back_populates="review_runs")
    review_prep: Mapped[ReviewPrep] = relationship(back_populates="review_runs")
    results: Mapped[list["ReviewResult"]] = relationship(back_populates="review_run", cascade="all, delete-orphan")
    asset_selection_results: Mapped[list["AssetSelectionResult"]] = relationship(
        back_populates="review_run",
        cascade="all, delete-orphan",
    )


class ReviewResult(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "review_result"
    __table_args__ = (UniqueConstraint("review_run_id", "submission_id", name="uq_review_result_run_submission"),)
    public_id_prefix = "rres"

    review_run_id: Mapped[int] = mapped_column(ForeignKey("review_run.id"), nullable=False, index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id"), nullable=False, index=True)
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_scale: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    review_run: Mapped[ReviewRun] = relationship(back_populates="results")
    submission: Mapped["Submission"] = relationship()
    item_results: Mapped[list["ReviewItemResult"]] = relationship(back_populates="review_result", cascade="all, delete-orphan")


class ReviewItemResult(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "review_item_result"
    public_id_prefix = "rires"

    review_result_id: Mapped[int] = mapped_column(ForeignKey("review_result.id"), nullable=False, index=True)
    question_item_id: Mapped[int] = mapped_column(ForeignKey("review_question_item.id"), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    review_result: Mapped[ReviewResult] = relationship(back_populates="item_results")
    question_item: Mapped[ReviewQuestionItem] = relationship(back_populates="item_results")


class AssetSelectionResult(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "asset_selection_result"
    public_id_prefix = "asr"

    review_run_id: Mapped[int] = mapped_column(ForeignKey("review_run.id"), nullable=False, index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id"), nullable=False, index=True)
    selected_assets_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    ignored_assets_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)

    review_run: Mapped[ReviewRun] = relationship(back_populates="asset_selection_results")
    submission: Mapped["Submission"] = relationship()
