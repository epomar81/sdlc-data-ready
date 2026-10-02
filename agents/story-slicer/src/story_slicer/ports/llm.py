"""Provider-neutral model requests, responses, and usage."""

from typing import Protocol

from pydantic import ConfigDict, Field, JsonValue

from story_slicer.domain.models import NonBlank, RequirementDocument
from story_slicer.ports.contracts import ContractModel, NonNegativeInteger


class TokenUsage(ContractModel):
    """None means unavailable; zero means a known count of zero."""

    input_tokens: NonNegativeInteger | None = None
    output_tokens: NonNegativeInteger | None = None


class RepairFeedback(ContractModel):
    previous_response: str
    diagnostic: NonBlank


class GenerationRequest(ContractModel):
    model_config = ConfigDict(validate_by_name=True, serialize_by_alias=True)

    instructions: NonBlank
    requirement: RequirementDocument
    json_schema: dict[str, JsonValue] = Field(alias="schema")
    repair_feedback: RepairFeedback | None = None


class GenerationResult(ContractModel):
    """Raw output is deliberately unvalidated until the application parses it."""

    text: str
    usage: TokenUsage


class LLMPort(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate a response or raise ProviderError / SessionTimeoutError."""
        ...
