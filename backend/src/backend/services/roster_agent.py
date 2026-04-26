from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from langchain_openai import ChatOpenAI
from pypdf import PdfReader

from backend.config import Settings, get_settings
from backend.services.llm_utils import extract_json, stringify_content


PREVIEW_MAX_ROWS = 40
PREVIEW_MAX_COLS = 12


@dataclass(slots=True)
class RosterFieldLayout:
    field: str
    column: int | None = None
    token_index: int | None = None


@dataclass(slots=True)
class RosterLayout:
    layout_type: str
    data_row_start: int
    data_row_end: int | None = None
    fields: list[RosterFieldLayout] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sheet_name: str | None = None


def read_csv_raw(file_path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with file_path.open("r", encoding=encoding, newline="") as handle:
                rows = list(csv.reader(handle))
            width = max((len(row) for row in rows), default=0)
            normalized_rows = [row + [""] * (width - len(row)) for row in rows]
            return pd.DataFrame(normalized_rows)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 编码无法识别，请转成 UTF-8 或 Excel 格式。")


def load_tabular_raw(file_path: Path) -> pd.DataFrame:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        dataframe = read_csv_raw(file_path)
    elif suffix in {".xlsx", ".xls"}:
        dataframe = pd.read_excel(file_path, header=None, dtype=str)
    else:
        raise ValueError(f"不支持的表格名单格式：{suffix}")
    dataframe = dataframe.fillna("")
    return dataframe


def build_tabular_preview(file_path: Path) -> str:
    dataframe = load_tabular_raw(file_path)
    lines: list[str] = []
    for row_index in range(min(len(dataframe.index), PREVIEW_MAX_ROWS)):
        row = dataframe.iloc[row_index].tolist()[:PREVIEW_MAX_COLS]
        cells = [f"C{column_index + 1}={str(cell).strip()}" for column_index, cell in enumerate(row)]
        lines.append(f"R{row_index + 1}: " + " | ".join(cells))
    return "\n".join(lines)


def split_pdf_line(line: str) -> list[str]:
    normalized = " ".join(line.split())
    if not normalized:
        return []
    tokens = [segment.strip() for segment in re.split(r"\t+|\s{2,}", line) if segment.strip()]
    if len(tokens) <= 1:
        tokens = normalized.split()
    return tokens


def build_pdf_preview(file_path: Path) -> str:
    reader = PdfReader(str(file_path))
    lines: list[str] = []
    line_number = 1
    for page_number, page in enumerate(reader.pages, start=1):
        for raw_line in (page.extract_text() or "").splitlines():
            normalized = " ".join(raw_line.split())
            if not normalized:
                continue
            tokens = split_pdf_line(raw_line)
            token_preview = " | ".join(f"C{index + 1}={token}" for index, token in enumerate(tokens[:PREVIEW_MAX_COLS]))
            lines.append(f"R{line_number} (P{page_number}): {token_preview or normalized}")
            line_number += 1
            if len(lines) >= PREVIEW_MAX_ROWS:
                return "\n".join(lines)
    return "\n".join(lines)


def parse_layout_payload(payload: dict) -> RosterLayout:
    fields: list[RosterFieldLayout] = []
    for item in payload.get("fields", []):
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field", "")).strip()
        if field_name not in {"name", "student_no", "class_name"}:
            continue
        column = item.get("column")
        token_index = item.get("token_index")
        fields.append(
            RosterFieldLayout(
                field=field_name,
                column=int(column) if column is not None else None,
                token_index=int(token_index) if token_index is not None else None,
            )
        )
    if not fields:
        raise ValueError("名单布局识别结果缺少有效字段。")
    return RosterLayout(
        layout_type=str(payload.get("layout_type", "table")).strip() or "table",
        data_row_start=int(payload.get("data_row_start", 1)),
        data_row_end=int(payload["data_row_end"]) if payload.get("data_row_end") is not None else None,
        fields=fields,
        notes=[str(item).strip() for item in payload.get("notes", []) if str(item).strip()],
        sheet_name=str(payload.get("sheet_name")).strip() if payload.get("sheet_name") else None,
    )


class RosterLayoutAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.llm_enabled:
            raise ValueError("未配置大模型，无法启用名单布局识别 Agent。")
        self.client = ChatOpenAI(
            model=self.settings.llm_model,
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_base_url,
            temperature=0,
        )

    def detect_layout(self, file_path: str | Path) -> RosterLayout:
        resolved = Path(file_path).expanduser().resolve()
        suffix = resolved.suffix.lower()
        if suffix in {".csv", ".xlsx", ".xls"}:
            preview = build_tabular_preview(resolved)
            source_kind = "tabular"
        elif suffix == ".pdf":
            preview = build_pdf_preview(resolved)
            source_kind = "pdf"
        else:
            raise ValueError("名单布局识别 Agent 仅支持 pdf / csv / xlsx / xls。")

        prompt = (
            "你是名单布局识别 Agent。你的任务不是提取学生名单，而是找出学生数据所在的行范围和字段列位置。"
            "请严格输出 JSON，不要输出任何解释。\n\n"
            "约束：\n"
            "1. 只允许字段名：name, student_no, class_name\n"
            "2. 行号和列号都使用 1 开始\n"
            "3. data_row_start 表示第一条学生数据所在行，不是表头行\n"
            "4. 若没有 class_name，可省略该字段\n"
            "5. 若是 PDF 且列不稳定，可使用 token_index 表示按空白拆分后的序号\n\n"
            'JSON 格式：{"layout_type":"table|line_tokens","data_row_start":5,"data_row_end":17,'
            '"fields":[{"field":"student_no","column":5},{"field":"name","column":6}],'
            '"notes":["前 1-4 行是说明"],"sheet_name":"Sheet1"}\n\n'
            f"文件类型：{source_kind}\n"
            f"文件名：{resolved.name}\n\n"
            "预览内容：\n"
            f"{preview or '（空）'}"
        )
        response = self.client.invoke(prompt)
        payload = extract_json(stringify_content(response.content))
        return parse_layout_payload(payload)
