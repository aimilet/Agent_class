from __future__ import annotations

from pathlib import Path

from backend.infra.file_ops.executor import execute_rename


def test_execute_rename_allows_same_directory_rename_outside_allowed_roots(tmp_path: Path) -> None:
    source = tmp_path / "第一次作业.docx"
    source.write_text("hello", encoding="utf-8")
    target = tmp_path / "张三_20250001_作业1.docx"

    result = execute_rename(source, target)

    assert result.executed is True
    assert not source.exists()
    assert target.exists()
