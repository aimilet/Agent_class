from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from backend.core.ids import generate_public_id


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class IntegerPrimaryKeyMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class PublicIdMixin:
    public_id_prefix: str = "obj"

    @declared_attr
    def public_id(cls) -> Mapped[str]:
        return mapped_column(
            String(40),
            default=lambda: generate_public_id(cls.public_id_prefix),
            unique=True,
            index=True,
            nullable=False,
        )

    @classmethod
    def build_public_id(cls) -> str:
        return generate_public_id(cls.public_id_prefix)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
