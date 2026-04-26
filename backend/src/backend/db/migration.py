from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from backend.db.migrations import get_migrations


class MigrationFn(Protocol):
    def __call__(self, connection: Connection) -> None: ...


@dataclass(slots=True)
class Migration:
    version: str
    description: str
    apply: MigrationFn


def _ensure_schema_migration_table(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migration (
                version VARCHAR(64) PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at VARCHAR(64) NOT NULL
            )
            """
        )
    )


def run_migrations(engine: Engine) -> None:
    migrations = get_migrations()
    with engine.begin() as connection:
        _ensure_schema_migration_table(connection)
        applied = {
            row[0]
            for row in connection.execute(text("SELECT version FROM schema_migration")).fetchall()
        }
        for migration in migrations:
            if migration.version in applied:
                continue
            migration.apply(connection)
            connection.execute(
                text(
                    """
                    INSERT INTO schema_migration (version, description, applied_at)
                    VALUES (:version, :description, :applied_at)
                    """
                ),
                {
                    "version": migration.version,
                    "description": migration.description,
                    "applied_at": datetime.now(UTC).isoformat(),
                },
            )
