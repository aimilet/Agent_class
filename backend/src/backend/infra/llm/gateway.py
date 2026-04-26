from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from backend.core.errors import DomainError
from backend.core.settings import Settings, get_settings
from backend.infra.llm.mock import MockStructuredLlm


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
        if self.settings.mock_llm_enabled:
            return self._mock.invoke(request)
        raise DomainError(
            "未配置可用的大模型。请设置 ZHUJIAO_LLM_BASE_URL / ZHUJIAO_LLM_API_KEY / ZHUJIAO_LLM_MODEL，或显式启用 mock LLM。",
            code="llm_not_configured",
            status_code=503,
        )
