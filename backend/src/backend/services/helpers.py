from __future__ import annotations

import re
from pathlib import Path


def slugify(text: str) -> str:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or "assignment"


def normalize_student_no(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", "", value.strip())
    return cleaned or None


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", value).strip().lower()


def filename_tokens(path: str | Path) -> set[str]:
    text = Path(path).name.lower()
    parts = re.split(r"[^a-z0-9\u4e00-\u9fff]+", text)
    return {part for part in parts if part}
