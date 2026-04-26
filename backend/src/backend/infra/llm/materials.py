from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.services.document_parser import DocumentParser
from backend.services.llm_utils import bytes_to_data_url
from backend.services.roster_agent import build_pdf_preview, build_tabular_preview


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
TABULAR_SUFFIXES = {".csv", ".xlsx", ".xls"}


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
