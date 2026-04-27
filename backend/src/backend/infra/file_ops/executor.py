from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.core.errors import DomainError
from backend.infra.storage.local import is_within_allowed_roots


@dataclass(slots=True)
class RenameExecutionResult:
    source_path: str
    target_path: str
    executed: bool
    reason: str | None = None


def preview_rename_command(source_path: str | Path, target_path: str | Path) -> str:
    source = Path(source_path).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()
    return f'mv "{source.as_posix()}" "{target.as_posix()}"'


def execute_rename(source_path: str | Path, target_path: str | Path) -> RenameExecutionResult:
    source = Path(source_path).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()
    if not source.exists():
        return RenameExecutionResult(str(source), str(target), executed=False, reason="源文件不存在")
    in_allowed_roots = is_within_allowed_roots(source) and is_within_allowed_roots(target.parent)
    same_directory_rename = source.parent == target.parent
    if not in_allowed_roots and not same_directory_rename:
        raise DomainError(
            "重命名目标超出受控根目录。",
            code="rename_out_of_scope",
            status_code=403,
            detail={"source": str(source), "target": str(target)},
        )
    if target.exists():
        return RenameExecutionResult(str(source), str(target), executed=False, reason="目标文件已存在")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return RenameExecutionResult(str(source), str(target), executed=True)
