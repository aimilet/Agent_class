from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.router import build_api_router
from backend.core.errors import register_exception_handlers
from backend.core.logging import configure_logging
from backend.core.settings import get_settings
from backend.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(build_api_router())
    return app


app = create_app()
