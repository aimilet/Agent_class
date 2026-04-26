from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from backend.services.roster_agent import (
    RosterLayout,
    load_tabular_raw,
    split_pdf_line,
    RosterLayoutAgent,
)


NAME_ALIASES = {
    "姓名",
    "学生姓名",
    "name",
    "studentname",
    "student",
}
NO_ALIASES = {
    "学号",
    "studentno",
    "studentid",
    "id",
    "number",
    "no",
}
CLASS_ALIASES = {
    "班级",
    "classname",
    "class",
}
HEADER_VALUE_ALIASES = NAME_ALIASES | NO_ALIASES | CLASS_ALIASES
NAME_PATTERN = re.compile(r"^[\u4e00-\u9fffA-Za-z·]{2,32}$")
PDF_PATTERNS = [
    re.compile(r"(?P<student_no>[A-Za-z0-9_-]{4,})\s+(?P<name>[\u4e00-\u9fffA-Za-z·]{2,})"),
    re.compile(r"(?P<name>[\u4e00-\u9fffA-Za-z·]{2,})\s+(?P<student_no>[A-Za-z0-9_-]{4,})"),
    re.compile(r"^(?P<name>[\u4e00-\u9fffA-Za-z·]{2,})$"),
]


@dataclass(slots=True)
class ImportedStudent:
    name: str
    student_no: str | None = None
    class_name: str | None = None
    source_filename: str | None = None


@dataclass(slots=True)
class StudentImportResult:
    students: list[ImportedStudent]
    parse_mode_used: str
    notes: list[str] = field(default_factory=list)


def _normalize_header(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s_\-()（）]+", "", text)


def _clean_cell(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _deduplicate(records: list[ImportedStudent]) -> list[ImportedStudent]:
    unique: dict[tuple[str | None, str, str | None], ImportedStudent] = {}
    for record in records:
        key = (
            record.student_no or None,
            record.name,
            record.class_name or None,
        )
        unique[key] = record
    return list(unique.values())


def _looks_like_header_value(value: str | None) -> bool:
    if not value:
        return False
    return _normalize_header(value) in HEADER_VALUE_ALIASES


def _is_plausible_name(value: str | None) -> bool:
    if not value:
        return False
    return bool(NAME_PATTERN.fullmatch(value.strip()))


def _resolve_columns(columns: list[object]) -> tuple[str | None, str | None, str | None]:
    name_column: str | None = None
    no_column: str | None = None
    class_column: str | None = None

    for column in columns:
        normalized = _normalize_header(column)
        if normalized in NAME_ALIASES:
            name_column = str(column)
        elif normalized in NO_ALIASES:
            no_column = str(column)
        elif normalized in CLASS_ALIASES:
            class_column = str(column)

    return name_column, no_column, class_column


def _find_header_row(dataframe: pd.DataFrame) -> int | None:
    search_rows = min(len(dataframe.index), 12)
    best_row: int | None = None
    best_score = 0

    for row_index in range(search_rows):
        cells = [_normalize_header(value) for value in dataframe.iloc[row_index].tolist()]
        score = 0
        for cell in cells:
            if cell in NAME_ALIASES:
                score += 4
            elif cell in NO_ALIASES or cell in CLASS_ALIASES:
                score += 2
        if score > best_score:
            best_score = score
            best_row = row_index

    if best_score <= 0:
        return None
    return best_row


def _build_dataframe_from_raw(dataframe: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []
    header_row = _find_header_row(dataframe)
    if header_row is None:
        columns = [f"col_{index + 1}" for index in range(len(dataframe.columns))]
        dataset = dataframe.copy()
        dataset.columns = columns
        notes.append("本地解析未识别明确表头，已按列序兜底。")
        return dataset, notes

    header = [str(value).strip() or f"col_{index + 1}" for index, value in enumerate(dataframe.iloc[header_row].tolist())]
    dataset = dataframe.iloc[header_row + 1 :].copy()
    dataset.columns = header
    notes.append(f"本地解析识别到第 {header_row + 1} 行为表头。")
    return dataset, notes


def _parse_dataframe_local(file_path: Path, class_name: str | None) -> StudentImportResult:
    raw = load_tabular_raw(file_path)
    raw = raw.replace("", pd.NA).dropna(how="all").fillna("")
    if raw.empty:
        return StudentImportResult(students=[], parse_mode_used="local_only", notes=["名单文件为空。"])

    dataframe, notes = _build_dataframe_from_raw(raw)
    name_column, no_column, class_column = _resolve_columns(list(dataframe.columns))
    if name_column is None:
        columns = [str(column) for column in dataframe.columns]
        if len(columns) == 1:
            name_column = columns[0]
        elif len(columns) >= 2:
            no_column = no_column or columns[0]
            name_column = columns[1]

    if name_column is None:
        raise ValueError("未识别到姓名列。")

    students: list[ImportedStudent] = []
    for _, row in dataframe.iterrows():
        name = _clean_cell(row.get(name_column))
        student_no = _clean_cell(row.get(no_column)) if no_column else None
        resolved_class_name = class_name or (_clean_cell(row.get(class_column)) if class_column else None)

        if _looks_like_header_value(name) or _looks_like_header_value(student_no):
            continue
        if not _is_plausible_name(name):
            continue

        students.append(
            ImportedStudent(
                name=name,
                student_no=student_no,
                class_name=resolved_class_name,
                source_filename=file_path.name,
            )
        )

    return StudentImportResult(
        students=_deduplicate(students),
        parse_mode_used="local_only",
        notes=notes,
    )


def _parse_pdf_local(file_path: Path, class_name: str | None) -> StudentImportResult:
    reader = PdfReader(str(file_path))
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    students: list[ImportedStudent] = []

    for raw_line in full_text.splitlines():
        line = " ".join(raw_line.split())
        if not line or any(token in line for token in ("姓名", "学号", "班级")):
            continue
        for pattern in PDF_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            name = _clean_cell(match.groupdict().get("name"))
            if not _is_plausible_name(name):
                continue
            students.append(
                ImportedStudent(
                    name=name,
                    student_no=_clean_cell(match.groupdict().get("student_no")),
                    class_name=class_name,
                    source_filename=file_path.name,
                )
            )
            break

    return StudentImportResult(
        students=_deduplicate(students),
        parse_mode_used="local_only",
        notes=[],
    )


def _extract_students_from_tabular_layout(
    file_path: Path,
    layout: RosterLayout,
    class_name: str | None,
) -> list[ImportedStudent]:
    dataframe = load_tabular_raw(file_path).replace("", pd.NA).dropna(how="all").fillna("")
    field_columns = {field.field: field.column for field in layout.fields if field.column is not None}
    if "name" not in field_columns:
        raise ValueError("名单布局识别缺少姓名列。")

    row_start = max(layout.data_row_start, 1)
    row_end = layout.data_row_end or len(dataframe.index)
    students: list[ImportedStudent] = []

    for row_number in range(row_start, min(row_end, len(dataframe.index)) + 1):
        row = dataframe.iloc[row_number - 1].tolist()

        def get_value(field_name: str) -> str | None:
            column_index = field_columns.get(field_name)
            if column_index is None or column_index <= 0 or column_index > len(row):
                return None
            return _clean_cell(row[column_index - 1])

        name = get_value("name")
        student_no = get_value("student_no")
        resolved_class_name = class_name or get_value("class_name")
        if _looks_like_header_value(name) or not _is_plausible_name(name):
            continue
        students.append(
            ImportedStudent(
                name=name,
                student_no=student_no,
                class_name=resolved_class_name,
                source_filename=file_path.name,
            )
        )
    return _deduplicate(students)


def _extract_students_from_pdf_layout(
    file_path: Path,
    layout: RosterLayout,
    class_name: str | None,
) -> list[ImportedStudent]:
    reader = PdfReader(str(file_path))
    lines: list[list[str]] = []
    for page in reader.pages:
        for raw_line in (page.extract_text() or "").splitlines():
            tokens = split_pdf_line(raw_line)
            if tokens:
                lines.append(tokens)

    field_columns = {
        field.field: (field.token_index or field.column)
        for field in layout.fields
        if (field.token_index or field.column) is not None
    }
    if "name" not in field_columns:
        raise ValueError("PDF 名单布局识别缺少姓名位置。")

    row_start = max(layout.data_row_start, 1)
    row_end = layout.data_row_end or len(lines)
    students: list[ImportedStudent] = []

    for row_number in range(row_start, min(row_end, len(lines)) + 1):
        tokens = lines[row_number - 1]

        def get_value(field_name: str) -> str | None:
            token_index = field_columns.get(field_name)
            if token_index is None or token_index <= 0 or token_index > len(tokens):
                return None
            return _clean_cell(tokens[token_index - 1])

        name = get_value("name")
        student_no = get_value("student_no")
        resolved_class_name = class_name or get_value("class_name")
        if _looks_like_header_value(name) or not _is_plausible_name(name):
            continue
        students.append(
            ImportedStudent(
                name=name,
                student_no=student_no,
                class_name=resolved_class_name,
                source_filename=file_path.name,
            )
        )

    return _deduplicate(students)


def _parse_with_agent_layout(file_path: Path, class_name: str | None) -> StudentImportResult:
    agent = RosterLayoutAgent()
    layout = agent.detect_layout(file_path)
    if file_path.suffix.lower() in {".csv", ".xlsx", ".xls"}:
        students = _extract_students_from_tabular_layout(file_path, layout, class_name)
    elif file_path.suffix.lower() == ".pdf":
        students = _extract_students_from_pdf_layout(file_path, layout, class_name)
    else:
        raise ValueError("Agent 布局识别不支持该名单格式。")

    notes = [*layout.notes, "已使用 Agent 识别字段位置并由 Python 自动抽取名单。"]
    return StudentImportResult(
        students=students,
        parse_mode_used="agent_layout",
        notes=notes,
    )


def _local_parse(file_path: Path, class_name: str | None) -> StudentImportResult:
    suffix = file_path.suffix.lower()
    if suffix in {".csv", ".xlsx", ".xls"}:
        return _parse_dataframe_local(file_path, class_name)
    if suffix == ".pdf":
        return _parse_pdf_local(file_path, class_name)
    raise ValueError("目前支持的名单导入格式为 pdf / csv / xlsx / xls。")


def _local_result_is_reliable(result: StudentImportResult) -> bool:
    if not result.students:
        return False
    plausible_names = sum(1 for student in result.students if _is_plausible_name(student.name))
    if plausible_names / max(len(result.students), 1) < 0.8:
        return False
    if len(result.students) == 1 and any("未识别明确表头" in note for note in result.notes):
        return False
    return True


def import_students_from_file(
    file_path: str | Path,
    class_name: str | None = None,
    parse_mode: str = "auto",
) -> StudentImportResult:
    resolved = Path(file_path).expanduser().resolve()
    if parse_mode not in {"local_only", "agent_layout", "auto"}:
        raise ValueError("名单解析模式必须是 local_only / agent_layout / auto。")

    if parse_mode == "local_only":
        return _local_parse(resolved, class_name)

    if parse_mode == "agent_layout":
        return _parse_with_agent_layout(resolved, class_name)

    local_result: StudentImportResult | None = None
    local_error: Exception | None = None
    try:
        local_result = _local_parse(resolved, class_name)
        if _local_result_is_reliable(local_result):
            local_result.parse_mode_used = "local_only"
            local_result.notes.append("自动模式判断本地解析结果可信。")
            return local_result
    except Exception as exc:  # pragma: no cover - 依赖输入文件实际内容
        local_error = exc

    try:
        agent_result = _parse_with_agent_layout(resolved, class_name)
        if local_result is not None and local_result.students:
            agent_result.notes.insert(0, f"自动模式放弃本地结果，原因：本地结果可信度不足（{len(local_result.students)} 条）。")
        elif local_error is not None:
            agent_result.notes.insert(0, f"自动模式本地解析失败：{local_error}")
        return agent_result
    except Exception as agent_exc:
        if local_result is not None and local_result.students:
            local_result.notes.append(f"自动模式尝试 Agent 失败，已回退本地结果：{agent_exc}")
            return local_result
        if local_error is not None:
            raise ValueError(f"本地解析失败：{local_error}；Agent 解析失败：{agent_exc}") from agent_exc
        raise
