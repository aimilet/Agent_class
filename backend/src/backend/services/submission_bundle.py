from __future__ import annotations

import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from backend.config import Settings, get_settings
from backend.services.document_parser import DocumentParser, VisualAsset


ARCHIVE_SUFFIXES = {
    ".zip",
    ".tar",
    ".tgz",
    ".tbz",
    ".tbz2",
    ".txz",
    ".gz",
    ".bz2",
    ".xz",
}
UNSUPPORTED_ARCHIVE_SUFFIXES = {".rar", ".7z"}


@dataclass(slots=True)
class BundleLogEntry:
    stage: str
    message: str
    level: str = "info"
    payload: dict[str, Any] | None = None


@dataclass(slots=True)
class SubmissionBundle:
    parser_name: str
    text: str
    notes: list[str]
    images_detected: int
    visual_assets: list[VisualAsset] = field(default_factory=list)
    included_files: list[str] = field(default_factory=list)
    logs: list[BundleLogEntry] = field(default_factory=list)


class SubmissionBundleParser:
    def __init__(self, parser: DocumentParser | None = None, settings: Settings | None = None) -> None:
        self.parser = parser or DocumentParser()
        self.settings = settings or get_settings()

    def parse_submission(self, submission_path: str | Path) -> SubmissionBundle:
        resolved = Path(submission_path).expanduser().resolve()
        if not resolved.exists():
            raise ValueError("提交路径不存在。")

        counter = {"leaf_files": 0}
        with TemporaryDirectory(dir=self.settings.artifacts_root, prefix="submission_bundle_") as temp_dir:
            bundle = self._parse_node(
                resolved,
                logical_path=resolved.name,
                scratch_root=Path(temp_dir),
                depth=0,
                counter=counter,
            )
        if not bundle.text.strip() and not bundle.visual_assets:
            raise ValueError("未从提交中提取到可审阅内容。")
        return bundle

    def _parse_node(
        self,
        path: Path,
        *,
        logical_path: str,
        scratch_root: Path,
        depth: int,
        counter: dict[str, int],
    ) -> SubmissionBundle:
        if depth > self.settings.submission_unpack_max_depth:
            raise ValueError(f"超过最大递归层数 {self.settings.submission_unpack_max_depth}，已停止展开。")

        if path.is_dir():
            return self._parse_directory(path, logical_path=logical_path, scratch_root=scratch_root, depth=depth, counter=counter)

        suffix = path.suffix.lower()
        if suffix in UNSUPPORTED_ARCHIVE_SUFFIXES:
            raise ValueError(f"暂不支持压缩格式：{suffix}。请先解压，或转换为 zip/tar 后再提交。")

        if not self.parser.supports(path):
            if self._is_archive(path):
                return self._parse_archive(
                    path,
                    logical_path=logical_path,
                    scratch_root=scratch_root,
                    depth=depth,
                    counter=counter,
                )
            raise ValueError(f"暂不支持的文件格式：{suffix or path.name}")

        counter["leaf_files"] += 1
        if counter["leaf_files"] > self.settings.submission_unpack_max_files:
            raise ValueError(f"提交内文件过多，超过上限 {self.settings.submission_unpack_max_files}。")

        parsed = self.parser.parse(path)
        return SubmissionBundle(
            parser_name=parsed.parser_name,
            text=parsed.text,
            notes=parsed.notes,
            images_detected=parsed.images_detected,
            visual_assets=parsed.visual_assets,
            included_files=[logical_path],
            logs=[
                BundleLogEntry(
                    stage="bundle_leaf_parse",
                    message="已解析文件",
                    payload={
                        "logical_path": logical_path,
                        "parser_name": parsed.parser_name,
                        "images_detected": parsed.images_detected,
                    },
                )
            ],
        )

    def _parse_directory(
        self,
        directory: Path,
        *,
        logical_path: str,
        scratch_root: Path,
        depth: int,
        counter: dict[str, int],
    ) -> SubmissionBundle:
        children = sorted(child for child in directory.iterdir() if not child.name.startswith("."))
        if not children:
            raise ValueError(f"目录为空：{logical_path}")

        bundles: list[tuple[str, SubmissionBundle]] = []
        logs = [
            BundleLogEntry(
                stage="bundle_expand_directory",
                message="开始展开目录",
                payload={"logical_path": logical_path, "child_count": len(children)},
            )
        ]
        for child in children:
            child_logical = f"{logical_path}/{child.name}"
            try:
                bundle = self._parse_node(
                    child,
                    logical_path=child_logical,
                    scratch_root=scratch_root,
                    depth=depth + 1,
                    counter=counter,
                )
                bundles.append((child_logical, bundle))
            except ValueError as exc:
                logs.append(
                    BundleLogEntry(
                        stage="bundle_skip_child",
                        message=str(exc),
                        level="warning",
                        payload={"logical_path": child_logical},
                    )
                )
        return self._merge_bundles(
            kind="directory",
            logical_path=logical_path,
            bundles=bundles,
            prefix_logs=logs,
        )

    def _parse_archive(
        self,
        archive_path: Path,
        *,
        logical_path: str,
        scratch_root: Path,
        depth: int,
        counter: dict[str, int],
    ) -> SubmissionBundle:
        extract_root = scratch_root / f"{archive_path.stem}_{depth}"
        extract_root.mkdir(parents=True, exist_ok=True)
        extracted_count = self._extract_archive(archive_path, extract_root)
        logs = [
            BundleLogEntry(
                stage="bundle_expand_archive",
                message="开始展开压缩包",
                payload={
                    "logical_path": logical_path,
                    "archive_path": str(archive_path),
                    "extracted_count": extracted_count,
                },
            )
        ]
        bundles: list[tuple[str, SubmissionBundle]] = []
        for child in sorted(extract_root.rglob("*")):
            if not child.exists() or not child.is_file():
                continue
            relative = child.relative_to(extract_root).as_posix()
            child_logical = f"{logical_path}/{relative}"
            try:
                bundle = self._parse_node(
                    child,
                    logical_path=child_logical,
                    scratch_root=scratch_root,
                    depth=depth + 1,
                    counter=counter,
                )
                bundles.append((child_logical, bundle))
            except ValueError as exc:
                logs.append(
                    BundleLogEntry(
                        stage="bundle_skip_archive_child",
                        message=str(exc),
                        level="warning",
                        payload={"logical_path": child_logical},
                    )
                )
        return self._merge_bundles(
            kind="archive",
            logical_path=logical_path,
            bundles=bundles,
            prefix_logs=logs,
        )

    def _merge_bundles(
        self,
        *,
        kind: str,
        logical_path: str,
        bundles: list[tuple[str, SubmissionBundle]],
        prefix_logs: list[BundleLogEntry],
    ) -> SubmissionBundle:
        if not bundles:
            raise ValueError(f"{logical_path} 中没有可解析的文件。")

        if len(bundles) == 1:
            _, only = bundles[0]
            only.logs = [*prefix_logs, *only.logs]
            return SubmissionBundle(
                parser_name=f"{kind}-bundle[{only.parser_name}]",
                text=only.text,
                notes=[f"{kind} 容器：{logical_path}", *only.notes],
                images_detected=only.images_detected,
                visual_assets=only.visual_assets,
                included_files=only.included_files,
                logs=only.logs,
            )

        sections: list[str] = []
        notes: list[str] = [f"{kind} 容器：{logical_path}", f"共汇总 {len(bundles)} 份可解析材料"]
        visual_assets: list[VisualAsset] = []
        images_detected = 0
        included_files: list[str] = []
        logs = list(prefix_logs)

        for child_logical, bundle in bundles:
            if bundle.text.strip():
                sections.append(f"[材料] {child_logical}\n{bundle.text}")
            notes.extend(f"{child_logical}: {note}" for note in bundle.notes)
            visual_assets.extend(bundle.visual_assets)
            images_detected += bundle.images_detected
            included_files.extend(bundle.included_files)
            logs.extend(bundle.logs)

        return SubmissionBundle(
            parser_name=f"{kind}-bundle",
            text="\n\n".join(section for section in sections if section.strip()),
            notes=notes,
            images_detected=images_detected,
            visual_assets=visual_assets,
            included_files=sorted(dict.fromkeys(included_files)),
            logs=logs,
        )

    def _is_archive(self, path: Path) -> bool:
        suffix = path.suffix.lower()
        return suffix in ARCHIVE_SUFFIXES or zipfile.is_zipfile(path) or tarfile.is_tarfile(path)

    def _extract_archive(self, archive_path: Path, extract_root: Path) -> int:
        if zipfile.is_zipfile(archive_path):
            return self._extract_zip(archive_path, extract_root)
        if tarfile.is_tarfile(archive_path):
            return self._extract_tar(archive_path, extract_root)
        raise ValueError(f"无法识别压缩格式：{archive_path.name}")

    def _extract_zip(self, archive_path: Path, extract_root: Path) -> int:
        extracted = 0
        root_resolved = extract_root.resolve()
        with zipfile.ZipFile(archive_path) as handle:
            for member in handle.infolist():
                target = (extract_root / member.filename).resolve()
                if root_resolved not in target.parents and target != root_resolved:
                    continue
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with handle.open(member) as source, target.open("wb") as sink:
                    sink.write(source.read())
                extracted += 1
        return extracted

    def _extract_tar(self, archive_path: Path, extract_root: Path) -> int:
        extracted = 0
        root_resolved = extract_root.resolve()
        with tarfile.open(archive_path) as handle:
            for member in handle.getmembers():
                target = (extract_root / member.name).resolve()
                if root_resolved not in target.parents and target != root_resolved:
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = handle.extractfile(member)
                if source is None:
                    continue
                with source, target.open("wb") as sink:
                    sink.write(source.read())
                extracted += 1
        return extracted
