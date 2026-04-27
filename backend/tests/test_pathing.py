from __future__ import annotations

from pathlib import Path

from backend.core.pathing import resolve_user_path
from backend.core.settings import Settings


def build_settings(runtime_root: Path) -> Settings:
    return Settings(runtime_root=str(runtime_root))


def test_resolve_windows_drive_path_to_wsl_mount(tmp_path: Path) -> None:
    mount_root = tmp_path / "mnt"
    expected = mount_root / "f" / "code_keyan" / "zhujiao_task" / "samples"
    expected.mkdir(parents=True)

    resolved = resolve_user_path(
        r"F:\code_keyan\zhujiao_task\samples",
        settings=build_settings(tmp_path / "runtime"),
        mount_root=mount_root,
    )

    assert resolved == expected.resolve()


def test_resolve_relative_path_against_extra_search_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "测试" / "第一次作业-学生提交"
    target.mkdir(parents=True)

    resolved = resolve_user_path(
        "测试/第一次作业-学生提交",
        settings=build_settings(tmp_path / "runtime"),
        extra_search_roots=[repo_root],
    )

    assert resolved == target.resolve()


def test_keep_existing_linux_path_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "already_linux"
    target.mkdir()

    resolved = resolve_user_path(str(target), settings=build_settings(tmp_path / "runtime"))

    assert resolved == target.resolve()
