from __future__ import annotations

from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path
import time
from typing import Any, TypeVar

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from backend.core.errors import DomainError
from backend.core.settings import Settings, get_settings
from backend.infra.llm.mock import MockStructuredLlm
from backend.services.llm_utils import bytes_to_data_url


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


@dataclass(slots=True)
class StructuredLlmRequest:
    system_prompt: str
    user_content: str | list[dict[str, Any]]
    output_model: type[StructuredModel]
    temperature: float = 0.0
    strict: bool = True
    model_name: str | None = None
    method: str | None = None


class LlmGateway:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._mock = MockStructuredLlm(self.settings)

    @property
    def configured(self) -> bool:
        return self.settings.llm_enabled

    @property
    def model_name(self) -> str:
        if self.settings.llm_enabled and self.settings.llm_model:
            return self.settings.llm_model
        return self.settings.mock_llm_model_name

    def invoke_structured(self, request: StructuredLlmRequest) -> StructuredModel:
        if self.settings.llm_enabled:
            mode = self.settings.llm_api_mode.strip().lower()
            if mode in {"responses", "response"}:
                return self._invoke_responses(request)
            if mode in {"chat", "chat_completions", "chat-completions"}:
                return self._invoke_chat_completions(request)
            try:
                return self._invoke_responses(request)
            except DomainError as exc:
                if exc.code != "llm_responses_api_unavailable":
                    raise
                return self._invoke_chat_completions(request)
        if self.settings.mock_llm_enabled:
            return self._mock.invoke(request)
        raise DomainError(
            "未配置可用的大模型。请设置 ZHUJIAO_LLM_BASE_URL / ZHUJIAO_LLM_API_KEY / ZHUJIAO_LLM_MODEL，或显式启用 mock LLM。",
            code="llm_not_configured",
            status_code=503,
        )

    def _invoke_chat_completions(self, request: StructuredLlmRequest) -> StructuredModel:
        client = ChatOpenAI(
            model=request.model_name or self.settings.llm_model,
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_base_url,
            temperature=request.temperature,
            timeout=self.settings.llm_timeout_seconds,
            max_retries=self.settings.llm_max_retries,
        )
        runnable = client.with_structured_output(
            request.output_model,
            method=request.method or self.settings.llm_json_method,
            strict=request.strict,
        )
        messages = [
            SystemMessage(content=request.system_prompt),
            HumanMessage(content=request.user_content),
        ]
        result = runnable.invoke(messages)
        if isinstance(result, request.output_model):
            return result
        return request.output_model.model_validate(result)

    def _invoke_responses(self, request: StructuredLlmRequest) -> StructuredModel:
        payload = {
            "model": request.model_name or self.settings.llm_model,
            "instructions": request.system_prompt,
            "input": self._build_responses_input(request.user_content),
            "temperature": request.temperature,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.output_model.__name__,
                    "schema": request.output_model.model_json_schema(),
                    "strict": False,
                }
            },
        }
        response = self._post_responses(payload)
        output_text = self._extract_response_text(response)
        if not output_text:
            raise DomainError(
                "Responses API 未返回可解析文本。",
                code="llm_empty_response",
                status_code=502,
            )
        try:
            return request.output_model.model_validate_json(output_text)
        except ValueError:
            return request.output_model.model_validate(json.loads(output_text))

    def _post_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.llm_base_url or not self.settings.llm_api_key:
            raise DomainError(
                "Responses API 配置不完整。",
                code="llm_not_configured",
                status_code=503,
            )
        url = f"{self.settings.llm_base_url.rstrip('/')}/responses"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        retry_count = max(0, self.settings.llm_max_retries)
        last_error: DomainError | None = None
        with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
            for attempt in range(retry_count + 1):
                try:
                    response = client.post(url, headers=headers, json=payload)
                except httpx.RequestError as exc:
                    last_error = DomainError(
                        "Responses API 网络请求失败。",
                        code="llm_responses_api_request_failed",
                        status_code=502,
                        detail={"error": str(exc)},
                    )
                    if attempt < retry_count:
                        time.sleep(min(2**attempt, 8))
                        continue
                    raise last_error from exc

                if response.status_code < 400:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise DomainError(
                            "Responses API 返回了非 JSON 内容。",
                            code="llm_invalid_response",
                            status_code=502,
                            detail={"body": response.text[:1000]},
                        ) from exc

                code = (
                    "llm_responses_api_unavailable"
                    if response.status_code in {404, 405}
                    else "llm_responses_api_error"
                )
                last_error = DomainError(
                    "Responses API 调用失败。",
                    code=code,
                    status_code=502,
                    detail={"status_code": response.status_code, "body": response.text[:1000]},
                )
                if response.status_code in {408, 409, 429, 500, 502, 503, 504} and attempt < retry_count:
                    time.sleep(min(2**attempt, 8))
                    continue
                raise last_error
        if last_error:
            raise last_error
        raise DomainError("Responses API 调用失败。", code="llm_responses_api_error", status_code=502)

    def _build_responses_input(self, content: str | list[dict[str, Any]]) -> str | list[dict[str, Any]]:
        if isinstance(content, str):
            return content
        response_content: list[dict[str, Any]] = []
        for item in content:
            if item.get("type") == "text":
                response_content.append({"type": "input_text", "text": str(item.get("text", ""))})
            elif item.get("type") == "image_url":
                image_url = item.get("image_url") or {}
                response_content.append(
                    {
                        "type": "input_image",
                        "image_url": image_url.get("url", ""),
                        "detail": item.get("detail", "auto"),
                    }
                )
            elif item.get("type") in {"file", "input_file"}:
                file_part = self._build_input_file_part(item)
                if file_part:
                    response_content.append(file_part)
        return [{"role": "user", "content": response_content}]

    def _build_input_file_part(self, item: dict[str, Any]) -> dict[str, Any] | None:
        if item.get("type") == "input_file":
            return item
        file_info = item.get("file") or {}
        file_id = file_info.get("file_id")
        if file_id:
            return {"type": "input_file", "file_id": file_id}
        file_data = file_info.get("file_data")
        filename = file_info.get("filename")
        if file_data:
            part = {"type": "input_file", "file_data": file_data}
            if filename:
                part["filename"] = str(filename)
            return part
        raw_path = file_info.get("path")
        if not raw_path:
            return None
        path = Path(raw_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            return None
        filename = str(filename or path.name)
        mime_type = file_info.get("mime_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return {
            "type": "input_file",
            "filename": filename,
            "file_data": bytes_to_data_url(path.read_bytes(), mime_type),
        }

    def _extract_response_text(self, response: Any) -> str:
        direct = getattr(response, "output_text", None)
        if direct:
            return str(direct)
        if isinstance(response, dict):
            data = response
        elif hasattr(response, "model_dump"):
            data = response.model_dump()
        else:
            data = {}
        texts: list[str] = []
        for output in data.get("output", []):
            for content in output.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    texts.append(content["text"])
        return "\n".join(texts)
