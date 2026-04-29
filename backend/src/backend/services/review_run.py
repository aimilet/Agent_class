from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.core.background_jobs import BackgroundJobCancelled, get_background_job_registry
from backend.core.errors import DomainError
from backend.core.runtime_review_settings import RuntimeReviewSettingsStore
from backend.core.settings import get_settings
from backend.db.session import SessionLocal
from backend.db.repositories import ApprovalRepository, AssignmentRepository
from backend.domain.models import ApprovalTask, ReviewPrep, ReviewResult, ReviewRun, Submission
from backend.graphs.review_run_parent_graph import ReviewRunParentGraph
from backend.infra.observability import AuditService


class ReviewRunService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.assignment_repo = AssignmentRepository(session)
        self.approval_repo = ApprovalRepository(session)
        self.audit_service = AuditService(session)
        self.settings = get_settings()
        self.runtime_settings_store = RuntimeReviewSettingsStore(self.settings)
        self.job_registry = get_background_job_registry()

    def create_review_run(self, *, assignment_public_id: str, review_prep_public_id: str | None, parallelism: int | None) -> ReviewRun:
        assignment = self.assignment_repo.get_by_public_id(assignment_public_id)
        runtime_settings = self.runtime_settings_store.load()
        if review_prep_public_id is None:
            if assignment.review_prep is None:
                raise DomainError("作业尚未绑定评审初始化版本。", code="review_prep_required", status_code=409)
            review_prep = assignment.review_prep
        else:
            review_prep = assignment.review_prep
            if review_prep is None or review_prep.public_id != review_prep_public_id:
                raise DomainError("指定的评审初始化版本不可用。", code="review_prep_mismatch", status_code=409)
        review_run = ReviewRun(
            public_id=ReviewRun.build_public_id(),
            assignment_id=assignment.id,
            review_prep_id=review_prep.id,
            status="queued",
            parallelism=parallelism or runtime_settings.review_run_default_parallelism,
        )
        self.session.add(review_run)
        self.audit_service.record(
            event_type="review_run_created",
            object_type="review_run",
            object_public_id=review_run.public_id,
            payload={"assignment_public_id": assignment.public_id},
        )
        self.session.commit()
        return review_run

    def start_review_run(self, *, review_run_public_id: str, operator_id: str = "system") -> ReviewRun:
        review_run = self.get_review_run(review_run_public_id)
        if self.job_registry.is_active("review_run", review_run.public_id):
            raise DomainError("正式评审已在运行中。", code="review_run_running", status_code=409)
        review_run.status = "selecting_assets"
        review_run.assignment.status = "reviewing"
        self.audit_service.record(
            event_type="review_run_start_requested",
            object_type="review_run",
            object_public_id=review_run.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        self.job_registry.start(
            object_type="review_run",
            object_public_id=review_run.public_id,
            label="正式评审 Agent",
            target=lambda: self._run_review_run_in_background(review_run.public_id, operator_id, False),
        )
        return review_run

    def cancel_review_run(self, *, review_run_public_id: str, operator_id: str = "system") -> ReviewRun:
        review_run = self.get_review_run(review_run_public_id)
        if not self.job_registry.request_cancel("review_run", review_run.public_id):
            raise DomainError("当前没有可停止的正式评审任务。", code="review_run_not_running", status_code=409)
        self.audit_service.record(
            event_type="review_run_cancel_requested",
            object_type="review_run",
            object_public_id=review_run.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        return review_run

    def get_review_run(self, review_run_public_id: str) -> ReviewRun:
        review_run = self.session.scalar(
            select(ReviewRun)
            .options(
                selectinload(ReviewRun.assignment),
                selectinload(ReviewRun.review_prep).selectinload(ReviewPrep.question_items),
                selectinload(ReviewRun.results).selectinload(ReviewResult.item_results),
                selectinload(ReviewRun.results)
                .selectinload(ReviewResult.submission)
                .selectinload(Submission.enrollment),
            )
            .where(ReviewRun.public_id == review_run_public_id)
        )
        if review_run is None:
            raise DomainError("评审运行不存在。", code="review_run_not_found", status_code=404)
        return review_run

    def list_results(self, review_run_public_id: str) -> list[ReviewResult]:
        review_run = self.get_review_run(review_run_public_id)
        return review_run.results

    def manual_review(self, *, review_result_public_id: str, total_score: float, summary: str, decision: str, operator_id: str = "system") -> ReviewResult:
        result = self.session.scalar(
            select(ReviewResult).where(ReviewResult.public_id == review_result_public_id)
        )
        if result is None:
            raise DomainError("评审结果不存在。", code="review_result_not_found", status_code=404)
        result.total_score = total_score
        result.summary = summary
        result.decision = decision
        result.status = "finalized"
        self.audit_service.record(
            event_type="review_result_manually_updated",
            object_type="review_result",
            object_public_id=result.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        return result

    def retry_failed(self, *, review_run_public_id: str, operator_id: str = "system") -> ReviewRun:
        review_run = self.get_review_run(review_run_public_id)
        if self.job_registry.is_active("review_run", review_run.public_id):
            raise DomainError("正式评审已在运行中。", code="review_run_running", status_code=409)
        review_run.status = "selecting_assets"
        self.session.commit()
        self.job_registry.start(
            object_type="review_run",
            object_public_id=review_run.public_id,
            label="正式评审重试",
            target=lambda: self._run_review_run_in_background(review_run.public_id, operator_id, True),
        )
        return review_run

    def publish(self, *, review_run_public_id: str, operator_id: str = "system"):
        review_run = self.get_review_run(review_run_public_id)
        existing_task = self._get_active_publish_task(review_run.public_id)
        if existing_task is not None:
            return existing_task
        publishable_results = [result for result in review_run.results if result.status in {"validated", "finalized"}]
        if not publishable_results:
            raise DomainError("当前评审运行没有可发布的评审结果。", code="no_publishable_review_results", status_code=409)
        task = self.approval_repo.create(
            object_type="review_run",
            object_public_id=review_run.public_id,
            action_type="publish",
            title="评审结果发布审批",
            summary=f"准备发布 {len(publishable_results)} 条评审结果。",
            command_preview_json=[
                {"review_result_public_id": result.public_id, "action": "publish"}
                for result in publishable_results
            ],
        )
        for result in publishable_results:
            self.approval_repo.add_item(
                task,
                item_type="publish_review_result",
                before_json={"status": result.status},
                after_json={"status": "published"},
                risk_level="high",
            )
        self.audit_service.record(
            event_type="review_run_publish_submitted",
            object_type="review_run",
            object_public_id=review_run.public_id,
            actor_type="user",
            actor_id=operator_id,
            payload={"approval_task_public_id": task.public_id},
        )
        self.session.commit()
        return task

    def _get_active_publish_task(self, review_run_public_id: str) -> ApprovalTask | None:
        return self.session.scalar(
            select(ApprovalTask)
            .options(selectinload(ApprovalTask.items))
            .where(
                ApprovalTask.object_type == "review_run",
                ApprovalTask.object_public_id == review_run_public_id,
                ApprovalTask.action_type == "publish",
                ApprovalTask.status.in_(["pending", "approved", "executing"]),
            )
            .order_by(ApprovalTask.updated_at.desc(), ApprovalTask.id.desc())
        )

    def _run_review_run_in_background(self, review_run_public_id: str, operator_id: str, retry_failed: bool) -> None:
        session = SessionLocal()
        try:
            service = ReviewRunService(session)
            service._execute_review_run(
                review_run_public_id=review_run_public_id,
                operator_id=operator_id,
                retry_failed=retry_failed,
            )
        finally:
            session.close()

    def _execute_review_run(self, *, review_run_public_id: str, operator_id: str, retry_failed: bool) -> None:
        review_run = self.get_review_run(review_run_public_id)
        try:
            if retry_failed:
                for result in list(review_run.results):
                    if result.status == "needs_manual_review":
                        result.status = "draft"
            graph = ReviewRunParentGraph(self.session)
            graph.invoke(review_run_public_id=review_run.public_id, operator_id=operator_id)
            self.session.commit()
        except BackgroundJobCancelled:
            self.session.rollback()
            self._mark_review_run_cancelled(review_run_public_id=review_run_public_id, operator_id=operator_id)
        except Exception as exc:
            self.session.rollback()
            self._mark_review_run_failed(
                review_run_public_id=review_run_public_id,
                operator_id=operator_id,
                error_message=str(exc),
            )

    def _mark_review_run_cancelled(self, *, review_run_public_id: str, operator_id: str) -> None:
        review_run = self.get_review_run(review_run_public_id)
        review_run.status = "cancelled"
        review_run.assignment.status = "review_prep_ready"
        review_run.summary_json = {**(review_run.summary_json or {}), "cancelled": True}
        self.audit_service.record(
            event_type="review_run_cancelled",
            object_type="review_run",
            object_public_id=review_run.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()

    def _mark_review_run_failed(self, *, review_run_public_id: str, operator_id: str, error_message: str) -> None:
        review_run = self.get_review_run(review_run_public_id)
        review_run.status = "failed"
        review_run.assignment.status = "review_prep_ready"
        review_run.summary_json = {**(review_run.summary_json or {}), "error_message": error_message}
        self.audit_service.record(
            event_type="review_run_failed",
            object_type="review_run",
            object_public_id=review_run.public_id,
            actor_type="user",
            actor_id=operator_id,
            payload={"error_message": error_message},
        )
        self.session.commit()
