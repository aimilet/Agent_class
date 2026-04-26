from __future__ import annotations

import uvicorn

from backend.app import app
from backend.core.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
