from __future__ import annotations

import base64
import json
import re
from typing import Any


def stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError("没有找到 JSON 对象")
    return json.loads(match.group(0))


def bytes_to_data_url(data: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def clamp_score(score: float | int | None) -> float:
    if score is None:
        return 0.0
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return 0.0
    return round(min(100.0, max(0.0, numeric)), 2)
