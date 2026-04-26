from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, Sequence

from rapidfuzz import fuzz

from backend.models import RenameRule, Student


INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')
MULTI_SPACE = re.compile(r"\s+")


@dataclass(slots=True)
class RenameOperation:
    source_path: str
    target_path: str | None
    matched_student: str | None
    confidence: float
    status: str
    reason: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class RenameRuleLike(Protocol):
    template: str
    assignment_label_default: str | None
    match_threshold: float


@dataclass(slots=True)
class RenameRuleSpec:
    template: str
    assignment_label_default: str | None = None
    match_threshold: float = 76.0


def normalize_text(value: str) -> str:
    text = value.strip().lower()
    return re.sub(r"[\W_]+", "", text)


def sanitize_segment(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        text = fallback
    text = INVALID_FILENAME_CHARS.sub("_", text)
    text = MULTI_SPACE.sub("_", text)
    return text.strip("._") or fallback


def find_best_student_match(
    file_stem: str,
    students: Sequence[Student],
    threshold: float,
) -> tuple[Student | None, float, str | None]:
    normalized_stem = normalize_text(file_stem)
    if not normalized_stem:
        return None, 0.0, "空文件名无法匹配"

    for student in students:
        student_no = normalize_text(student.student_no or "")
        student_name = normalize_text(student.name)
        if student_no and student_no in normalized_stem:
            return student, 100.0, "命中文件名中的学号"
        if student_name and student_name in normalized_stem:
            return student, 100.0, "命中文件名中的姓名"

    best_student: Student | None = None
    best_score = 0.0
    for student in students:
        candidates = [
            normalize_text(student.name),
            normalize_text(student.student_no or ""),
            normalize_text(f"{student.student_no or ''}{student.name}"),
            normalize_text(f"{student.name}{student.student_no or ''}"),
        ]
        score = max((fuzz.partial_ratio(normalized_stem, candidate) for candidate in candidates if candidate), default=0)
        if score > best_score:
            best_score = float(score)
            best_student = student

    if best_student and best_score >= threshold:
        return best_student, best_score, "模糊匹配"
    return None, best_score, "未达到匹配阈值"


def _render_target_name(
    source_path: Path,
    rule: RenameRule | RenameRuleSpec | RenameRuleLike,
    student: Student,
    assignment_label: str | None,
) -> str:
    rendered = rule.template.format(
        assignment=sanitize_segment(assignment_label or rule.assignment_label_default, "作业"),
        student_no=sanitize_segment(student.student_no, "unknown"),
        name=sanitize_segment(student.name, "unknown"),
        class_name=sanitize_segment(student.class_name, "未分班"),
        original_stem=sanitize_segment(source_path.stem, "原文件"),
    )
    rendered = sanitize_segment(rendered, "未命名作业")
    return f"{rendered}{source_path.suffix.lower()}"


def preview_renames(
    directory_path: str | Path,
    rule: RenameRule | RenameRuleSpec | RenameRuleLike,
    students: Sequence[Student],
    assignment_label: str | None = None,
) -> list[RenameOperation]:
    directory = Path(directory_path).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("改名目录不存在，或不是文件夹。")

    operations: list[RenameOperation] = []
    for file_path in sorted(path for path in directory.iterdir() if path.is_file()):
        student, confidence, reason = find_best_student_match(file_path.stem, students, rule.match_threshold)
        if student is None:
            operations.append(
                RenameOperation(
                    source_path=str(file_path),
                    target_path=None,
                    matched_student=None,
                    confidence=round(confidence, 2),
                    status="unmatched",
                    reason=reason,
                )
            )
            continue

        try:
            target_name = _render_target_name(file_path, rule, student, assignment_label)
        except KeyError as exc:
            operations.append(
                RenameOperation(
                    source_path=str(file_path),
                    target_path=None,
                    matched_student=student.name,
                    confidence=round(confidence, 2),
                    status="error",
                    reason=f"模板变量不存在：{exc}",
                )
            )
            continue

        target_path = file_path.with_name(target_name)
        status = "unchanged" if target_path == file_path else "ready"
        operations.append(
            RenameOperation(
                source_path=str(file_path),
                target_path=str(target_path),
                matched_student=student.name,
                confidence=round(confidence, 2),
                status=status,
                reason=reason,
            )
        )

    return operations


def apply_renames(operations: Sequence[RenameOperation]) -> tuple[int, list[RenameOperation]]:
    renamed_count = 0
    applied: list[RenameOperation] = []
    reserved_targets: set[Path] = set()

    for item in operations:
        source = Path(item.source_path)
        if item.status not in {"ready", "unchanged"} or item.target_path is None:
            applied.append(item)
            continue

        target = Path(item.target_path)
        if item.status == "unchanged":
            applied.append(item)
            continue

        counter = 1
        while (target.exists() and target != source) or target in reserved_targets:
            target = target.with_name(f"{target.stem}_{counter}{target.suffix}")
            counter += 1

        source.rename(target)
        renamed_count += 1
        reserved_targets.add(target)
        applied.append(
            RenameOperation(
                source_path=str(source),
                target_path=str(target),
                matched_student=item.matched_student,
                confidence=item.confidence,
                status="renamed",
                reason=item.reason,
            )
        )

    return renamed_count, applied
