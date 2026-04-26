from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from backend.services.document_parser import CODE_SUFFIXES, TEXT_SUFFIXES, DocumentParser
from backend.services.llm_utils import bytes_to_data_url
from backend.services.roster_agent import build_pdf_preview, build_tabular_preview


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
TABULAR_SUFFIXES = {".csv", ".xlsx", ".xls"}
ARCHIVE_SUFFIXES = {".zip", ".tar", ".tgz", ".tbz", ".tbz2", ".txz", ".gz", ".bz2", ".xz"}


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[已截断]"


def build_material_message_parts(
    materials: list[dict[str, Any]],
    *,
    text_limit: int = 12000,
    image_limit: int = 4,
) -> list[dict[str, Any]]:
    parser = DocumentParser()
    parts: list[dict[str, Any]] = []
    images_used = 0

    for index, item in enumerate(materials, start=1):
        path = Path(item["path"]).expanduser().resolve()
        suffix = path.suffix.lower()
        header = f"[材料 {index}] 文件名：{item.get('filename') or path.name}\n路径：{path}"
        direct_parts = build_file_message_parts([item], image_limit=image_limit - images_used)
        if direct_parts:
            parts.append({"type": "text", "text": header + "\n文件已作为原始附件提供，请直接读取附件内容。"})
            parts.extend(direct_parts)
            images_used += sum(1 for part in direct_parts if part.get("type") == "image_url")
            continue
        if suffix in IMAGE_SUFFIXES:
            parts.append({"type": "text", "text": header + "\n文件类型：图片"})
            if images_used < image_limit:
                mime_type = item.get("mime_type") or f"image/{suffix.lstrip('.') or 'png'}"
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": bytes_to_data_url(path.read_bytes(), mime_type)},
                    }
                )
                images_used += 1
            continue

        if suffix in TABULAR_SUFFIXES:
            preview = build_tabular_preview(path)
            parts.append({"type": "text", "text": header + "\n表格预览：\n" + _truncate(preview, text_limit)})
            continue

        if suffix == ".pdf":
            preview = build_pdf_preview(path)
            parts.append({"type": "text", "text": header + "\nPDF 预览：\n" + _truncate(preview, text_limit)})
            continue

        parsed = parser.parse(path)
        body = parsed.text.strip() or "\n".join(parsed.notes) or "无可解析文本"
        parts.append({"type": "text", "text": header + "\n内容预览：\n" + _truncate(body, text_limit)})
        for asset in parsed.visual_assets:
            if images_used >= image_limit:
                break
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": bytes_to_data_url(asset.data, asset.mime_type)},
                }
            )
            images_used += 1
    return parts


def build_file_message_parts(
    items: list[dict[str, Any]],
    *,
    path_key: str = "path",
    filename_key: str = "filename",
    image_limit: int = 8,
    text_limit: int = 40000,
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    images_used = 0
    for item in items:
        raw_path = item.get(path_key) or item.get("real_path")
        if not raw_path:
            continue
        path = Path(raw_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            continue
        filename = str(item.get(filename_key) or item.get("logical_path") or path.name)
        mime_type = item.get("mime_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        suffix = path.suffix.lower()
        if suffix in ARCHIVE_SUFFIXES:
            continue
        if suffix in TEXT_SUFFIXES | CODE_SUFFIXES:
            parts.append(
                {
                    "type": "text",
                    "text": f"[附件文本] {filename}\n{_truncate(_read_text_file(path), text_limit)}",
                }
            )
            continue
        if suffix in IMAGE_SUFFIXES:
            if images_used >= image_limit:
                continue
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": bytes_to_data_url(path.read_bytes(), mime_type)},
                    "detail": "high",
                }
            )
            images_used += 1
            continue
        parts.append(
            {
                "type": "file",
                "file": {
                    "path": str(path),
                    "filename": filename,
                    "mime_type": mime_type,
                },
            }
        )
    return parts


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="replace")
