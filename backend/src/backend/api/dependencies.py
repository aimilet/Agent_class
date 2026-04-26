from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from backend.core.settings import Settings, get_settings
from backend.db.session import get_session


def get_db() -> Generator[Session, None, None]:
    yield from get_session()


def get_app_settings() -> Settings:
    return get_settings()
