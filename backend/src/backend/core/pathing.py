from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from backend.core.settings import Settings, get_settings


WINDOWS_DRIVE_PATTERN = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$")
WSL_UNC_PREFIXES = ("\\\\wsl$\\", "\\\\wsl.localhost\\")


def resolve_user_path(
    raw_path: str | Path,
    *,
    settings: Settings | None = None,
    extra_search_roots: Iterable[Path] | None = None,
    mount_root: Path = Path("/mnt"),
) -> Path:
    settings = settings or get_settings()
    raw_text = str(raw_path).strip()
    if not raw_text:
        return Path(raw_path).expanduser()

    repo_root = settings.backend_root.parent.resolve()
    default_search_roots = (
        Path.cwd(),
        repo_root,
        settings.backend_root.resolve(),
        settings.resolved_runtime_root.resolve(),
    )
    search_roots = tuple(extra_search_roots or default_search_roots)

    candidates: list[Path] = []
    seen: set[str] = set()

    def push(candidate: Path) -> None:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)

    raw_path_obj = Path(raw_text).expanduser()
    push(raw_path_obj)

    normalized_text = raw_text.replace("\\", "/")
    if normalized_text != raw_text:
        push(Path(normalized_text).expanduser())

    if match := WINDOWS_DRIVE_PATTERN.match(raw_text):
        rest = match.group("rest").replace("\\", "/")
        push((mount_root / match.group("drive").lower() / rest).expanduser())
    elif match := WINDOWS_DRIVE_PATTERN.match(normalized_text):
        push((mount_root / match.group("drive").lower() / match.group("rest")).expanduser())

    lowered = raw_text.lower()
    if lowered.startswith(WSL_UNC_PREFIXES):
        parts = [part for part in raw_text.replace("/", "\\").split("\\") if part]
        if len(parts) >= 3:
            push(Path("/").joinpath(*parts[2:]).expanduser())

    for candidate in list(candidates):
        if candidate.is_absolute():
            continue
        for root in search_roots:
            push((root / candidate).expanduser())

    fallback: Path | None = None
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            continue
        if fallback is None:
            fallback = resolved
        if resolved.exists():
            return resolved
    return fallback or raw_path_obj


def normalize_user_path(raw_path: str | Path, *, settings: Settings | None = None) -> str:
    return str(resolve_user_path(raw_path, settings=settings))
