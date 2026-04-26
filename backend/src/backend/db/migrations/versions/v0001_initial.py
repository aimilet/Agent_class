from __future__ import annotations

from sqlalchemy.engine import Connection

from backend.db.base import Base


def apply(connection: Connection) -> None:
    import backend.domain.models  # noqa: F401

    Base.metadata.create_all(bind=connection)


from backend.db.migration import Migration

migration = Migration(version="0001_initial", description="创建后端重构后的核心表结构", apply=apply)
