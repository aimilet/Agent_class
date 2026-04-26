from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.settings import get_settings
from backend.db.repositories import AgentRunRepository
from backend.infra.llm import LlmGateway, StructuredLlmRequest
from backend.schemas.common import AgentInputEnvelope, AgentOutputEnvelope


class AgentHandler(Protocol):
    def __call__(self, envelope: AgentInputEnvelope) -> AgentOutputEnvelope: ...


@dataclass(slots=True)
class AgentExecutionResult:
    run_public_id: str
    output: AgentOutputEnvelope


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class StructuredAgent(Generic[StructuredModel]):
    name = "structured_agent"
    prompt_version = "v2.0.0"
    output_model: type[StructuredModel]
    temperature: float = 0.0

    def __init__(self, gateway: LlmGateway | None = None) -> None:
        self.settings = get_settings()
        self.gateway = gateway or LlmGateway(self.settings)

    @property
    def model_name(self) -> str:
        return self.gateway.model_name

    def build_request(self, envelope: AgentInputEnvelope) -> StructuredLlmRequest:
        raise NotImplementedError

    def build_response(self, result: StructuredModel, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        raise NotImplementedError

    def __call__(self, envelope: AgentInputEnvelope) -> AgentOutputEnvelope:
        request = self.build_request(envelope)
        result = self.gateway.invoke_structured(request)
        return self.build_response(result, envelope)


class AgentExecutor:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AgentRunRepository(session)

    def run(
        self,
        *,
        graph_name: str,
        stage_name: str,
        agent_name: str,
        prompt_version: str,
        model_name: str | None,
        envelope: AgentInputEnvelope,
        handler: AgentHandler,
    ) -> AgentExecutionResult:
        run = self.repository.create(
            graph_name=graph_name,
            agent_name=agent_name,
            stage_name=stage_name,
            status="running",
            model_name=model_name,
            prompt_version=prompt_version,
            input_ref_json=envelope.model_dump(mode="json"),
        )
        try:
            output = handler(envelope)
            self.repository.finish(
                run,
                status="succeeded" if output.status == "succeeded" else output.status,
                output_ref_json=output.model_dump(mode="json"),
            )
        except Exception as exc:
            self.repository.finish(run, status="failed", error_message=str(exc))
            raise
        return AgentExecutionResult(run_public_id=run.public_id, output=output)
