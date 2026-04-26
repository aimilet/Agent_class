from __future__ import annotations

from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.errors import DomainError
from backend.db.repositories import AssignmentRepository
from backend.domain.models import ReviewPrep, ReviewQuestionItem
from backend.graphs.review_prep_graph import ReviewPrepGraph
from backend.infra.observability import AuditService
from backend.infra.storage import save_upload


class ReviewPrepService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.assignment_repo = AssignmentRepository(session)
        self.audit_service = AuditService(session)

    async def create_review_prep(self, *, assignment_public_id: str, files: list[UploadFile]) -> ReviewPrep:
        assignment = self.assignment_repo.get_by_public_id(assignment_public_id)
        stored_files = [await save_upload(file, "review_prep") for file in files]
        version_no = (
            self.session.scalar(
                select(ReviewPrep.version_no)
                .where(ReviewPrep.assignment_id == assignment.id)
                .order_by(ReviewPrep.version_no.desc())
                .limit(1)
            )
            or 0
        )
        review_prep = ReviewPrep(
            public_id=ReviewPrep.build_public_id(),
            assignment_id=assignment.id,
            status="draft",
            source_materials_json=[
                {
                    "original_name": item.original_name,
                    "stored_name": item.stored_name,
                    "path": item.path,
                    "size_bytes": item.size_bytes,
                }
                for item in stored_files
            ],
            version_no=version_no + 1,
        )
        self.session.add(review_prep)
        self.audit_service.record(
            event_type="review_prep_created",
            object_type="review_prep",
            object_public_id=review_prep.public_id,
            payload={"assignment_public_id": assignment.public_id, "file_count": len(stored_files)},
        )
        self.session.commit()
        return review_prep

    def run_review_prep(self, *, review_prep_public_id: str, operator_id: str = "system") -> ReviewPrep:
        review_prep = self.session.scalar(select(ReviewPrep).where(ReviewPrep.public_id == review_prep_public_id))
        if review_prep is None:
            raise DomainError("评审初始化不存在。", code="review_prep_not_found", status_code=404)
        graph = ReviewPrepGraph(self.session)
        graph.invoke(review_prep_public_id=review_prep.public_id, operator_id=operator_id)
        self.session.commit()
        return review_prep

    def get_review_prep(self, review_prep_public_id: str) -> ReviewPrep:
        review_prep = self.session.scalar(select(ReviewPrep).where(ReviewPrep.public_id == review_prep_public_id))
        if review_prep is None:
            raise DomainError("评审初始化不存在。", code="review_prep_not_found", status_code=404)
        return review_prep

    def list_questions(self, review_prep_public_id: str) -> list[ReviewQuestionItem]:
        review_prep = self.get_review_prep(review_prep_public_id)
        return list(
            self.session.scalars(
                select(ReviewQuestionItem)
                .where(ReviewQuestionItem.review_prep_id == review_prep.id)
                .order_by(ReviewQuestionItem.question_no.asc())
            ).all()
        )

    def patch_question(self, *, item_public_id: str, payload: dict, operator_id: str = "system") -> ReviewQuestionItem:
        item = self.session.scalar(select(ReviewQuestionItem).where(ReviewQuestionItem.public_id == item_public_id))
        if item is None:
            raise DomainError("题目项不存在。", code="review_question_not_found", status_code=404)
        for key, value in payload.items():
            if value is not None:
                setattr(item, key, value)
        self.audit_service.record(
            event_type="review_question_updated",
            object_type="review_question_item",
            object_public_id=item.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        return item

    def confirm_review_prep(self, *, review_prep_public_id: str, operator_id: str = "system") -> ReviewPrep:
        review_prep = self.get_review_prep(review_prep_public_id)
        review_prep.status = "ready"
        review_prep.confirmed_at = datetime.now(UTC)
        review_prep.assignment.review_prep_id = review_prep.id
        review_prep.assignment.status = "review_prep_ready"
        self.audit_service.record(
            event_type="review_prep_confirmed",
            object_type="review_prep",
            object_public_id=review_prep.public_id,
            actor_type="user",
            actor_id=operator_id,
        )
        self.session.commit()
        return review_prep
