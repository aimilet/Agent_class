from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, utcnow


class Course(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "course"
    __table_args__ = (UniqueConstraint("course_code", "term", "class_label", name="uq_course_identity"),)
    public_id_prefix = "course"

    course_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    course_name: Mapped[str] = mapped_column(String(255), nullable=False)
    term: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    class_label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    teacher_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    active_roster_batch_id: Mapped[int | None] = mapped_column(ForeignKey("roster_import_batch.id"), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    enrollments: Mapped[list["CourseEnrollment"]] = relationship(back_populates="course")
    roster_import_batches: Mapped[list["RosterImportBatch"]] = relationship(
        back_populates="course",
        foreign_keys="RosterImportBatch.course_id",
    )
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="course")
    active_roster_batch: Mapped["RosterImportBatch | None"] = relationship(foreign_keys=[active_roster_batch_id])


class Person(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "person"
    public_id_prefix = "person"

    student_no_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    student_no_norm: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name_raw: Mapped[str] = mapped_column(String(128), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    enrollments: Mapped[list["CourseEnrollment"]] = relationship(back_populates="person")


class CourseEnrollment(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "course_enrollment"
    __table_args__ = (UniqueConstraint("course_id", "person_id", name="uq_course_enrollment_course_person"),)
    public_id_prefix = "enr"

    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), nullable=False, index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), nullable=False, index=True)
    display_student_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_roster_batch_id: Mapped[int | None] = mapped_column(ForeignKey("roster_import_batch.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    course: Mapped[Course] = relationship(back_populates="enrollments")
    person: Mapped[Person] = relationship(back_populates="enrollments")
    source_roster_batch: Mapped["RosterImportBatch | None"] = relationship(foreign_keys=[source_roster_batch_id])
    submissions: Mapped[list["Submission"]] = relationship(back_populates="enrollment")


class RosterImportBatch(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "roster_import_batch"
    public_id_prefix = "rib"

    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), nullable=False, index=True)
    source_files_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    parse_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded", index=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    course: Mapped[Course] = relationship(back_populates="roster_import_batches", foreign_keys=[course_id])
    candidate_rows: Mapped[list["RosterCandidateRow"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class RosterCandidateRow(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "roster_candidate_row"
    public_id_prefix = "rcr"

    batch_id: Mapped[int] = mapped_column(ForeignKey("roster_import_batch.id"), nullable=False, index=True)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    student_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    raw_fragment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped[RosterImportBatch] = relationship(back_populates="candidate_rows")


class Assignment(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "assignment"
    __table_args__ = (UniqueConstraint("course_id", "seq_no", name="uq_assignment_course_seq"),)
    public_id_prefix = "asg"

    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), nullable=False, index=True)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    review_prep_id: Mapped[int | None] = mapped_column(ForeignKey("review_prep.id"), nullable=True)

    course: Mapped[Course] = relationship(back_populates="assignments")
    submission_import_batches: Mapped[list["SubmissionImportBatch"]] = relationship(back_populates="assignment")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="assignment")
    naming_policies: Mapped[list["NamingPolicy"]] = relationship(back_populates="assignment")
    naming_plans: Mapped[list["NamingPlan"]] = relationship(back_populates="assignment")
    review_runs: Mapped[list["ReviewRun"]] = relationship(back_populates="assignment")
    review_prep: Mapped["ReviewPrep | None"] = relationship(foreign_keys=[review_prep_id])


class SubmissionImportBatch(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "submission_import_batch"
    public_id_prefix = "sib"

    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignment.id"), nullable=False, index=True)
    root_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    assignment: Mapped[Assignment] = relationship(back_populates="submission_import_batches")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="import_batch")


class Submission(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "submission"
    __table_args__ = (UniqueConstraint("assignment_id", "enrollment_id", name="uq_submission_assignment_enrollment"),)
    public_id_prefix = "sub"

    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignment.id"), nullable=False, index=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("submission_import_batch.id"), nullable=True, index=True)
    enrollment_id: Mapped[int | None] = mapped_column(ForeignKey("course_enrollment.id"), nullable=True, index=True)
    source_entry_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_entry_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    matched_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="discovered", index=True)
    canonical_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_path: Mapped[str] = mapped_column(String(2048), nullable=False)

    assignment: Mapped[Assignment] = relationship(back_populates="submissions")
    import_batch: Mapped[SubmissionImportBatch | None] = relationship(back_populates="submissions")
    enrollment: Mapped[CourseEnrollment | None] = relationship(back_populates="submissions")
    assets: Mapped[list["SubmissionAsset"]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    match_candidates: Mapped[list["SubmissionMatchCandidate"]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
    )


class SubmissionAsset(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "submission_asset"
    public_id_prefix = "asset"

    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id"), nullable=False, index=True)
    logical_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    real_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    asset_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_by_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    selected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_ignored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    submission: Mapped[Submission] = relationship(back_populates="assets")


class SubmissionMatchCandidate(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "submission_match_candidate"
    public_id_prefix = "smc"

    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id"), nullable=False, index=True)
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("course_enrollment.id"), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rank_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    submission: Mapped[Submission] = relationship(back_populates="match_candidates")


class NamingPolicy(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "naming_policy"
    public_id_prefix = "npol"

    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignment.id"), nullable=False, index=True)
    template_text: Mapped[str] = mapped_column(String(255), nullable=False)
    natural_language_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)

    assignment: Mapped[Assignment] = relationship(back_populates="naming_policies")
    naming_plans: Mapped[list["NamingPlan"]] = relationship(back_populates="policy")


class NamingPlan(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "naming_plan"
    public_id_prefix = "nplan"

    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignment.id"), nullable=False, index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("naming_policy.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated", index=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)
    approval_task_id: Mapped[int | None] = mapped_column(ForeignKey("approval_task.id"), nullable=True)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    assignment: Mapped[Assignment] = relationship(back_populates="naming_plans")
    policy: Mapped[NamingPolicy] = relationship(back_populates="naming_plans")
    operations: Mapped[list["NamingOperation"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    approval_task: Mapped["ApprovalTask | None"] = relationship(foreign_keys=[approval_task_id])


class NamingOperation(IntegerPrimaryKeyMixin, PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "naming_operation"
    public_id_prefix = "nop"

    plan_id: Mapped[int] = mapped_column(ForeignKey("naming_plan.id"), nullable=False, index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id"), nullable=False, index=True)
    source_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    target_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned", index=True)
    conflict_strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    command_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_info_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    plan: Mapped[NamingPlan] = relationship(back_populates="operations")
    submission: Mapped[Submission] = relationship()
