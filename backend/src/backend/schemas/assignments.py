from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from backend.schemas.common import TimestampedPublicRead


class AssignmentCreate(BaseModel):
    seq_no: int
    title: str
    description: str | None = None
    due_at: datetime | None = None


class AssignmentRead(TimestampedPublicRead):
    course_public_id: str
    seq_no: int
    title: str
    slug: str
    description: str | None
    due_at: datetime | None
    status: str
    review_prep_public_id: str | None = None
