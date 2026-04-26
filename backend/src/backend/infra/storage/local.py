from __future__ import annotations

import hashlib
from dataclasses import dataclass
from mimetypes import guess_type
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from backend.core.errors import DomainError
from backend.core.ids import generate_public_id
from backend.core.settings import get_settings


@dataclass(slots=True)
class StoredFile:
    original_name: str
    stored_name: str
    path: str
    size_bytes: int


def ensure_existing_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise DomainError("路径不存在。", code="path_not_found", status_code=404, detail={"path": str(resolved)})
    return resolved


def is_within_allowed_roots(path: Path) -> bool:
    settings = get_settings()
    return any(root == path or root in path.parents for root in settings.normalized_allowed_path_roots)


def ensure_mutable_path(path: str | Path) -> Path:
    resolved = ensure_existing_path(path)
    if not is_within_allowed_roots(resolved):
        raise DomainError(
            "目标路径不在受控根目录内。",
            code="path_not_allowed",
            status_code=403,
            detail={"path": str(resolved)},
        )
    return resolved


async def save_upload(file: UploadFile, namespace: str) -> StoredFile:
    settings = get_settings()
    original_name = Path(file.filename or "upload.bin").name
    suffix = Path(original_name).suffix
    stored_name = f"{generate_public_id(namespace)}{suffix}"
    target_dir = settings.uploads_root / namespace
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / stored_name
    content = await file.read()
    async with aiofiles.open(target_path, "wb") as handle:
        await handle.write(content)
    return StoredFile(
        original_name=original_name,
        stored_name=stored_name,
        path=str(target_path),
        size_bytes=len(content),
    )


def build_file_ref(path: str | Path, original_name: str | None = None) -> StoredFile:
    resolved = ensure_existing_path(path)
    return StoredFile(
        original_name=original_name or resolved.name,
        stored_name=resolved.name,
        path=str(resolved),
        size_bytes=resolved.stat().st_size,
    )


def sha256_for_file(path: str | Path) -> str:
    resolved = ensure_existing_path(path)
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mime_type_for_path(path: str | Path) -> str | None:
    return guess_type(str(path))[0]
