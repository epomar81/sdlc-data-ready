from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from intention_refiner.domain.integration import (
    PublicationResult,
    RequirementInput,
    SourceReference,
)

if TYPE_CHECKING:
    from intention_refiner.application.integrations import PublicationRequest


@dataclass(frozen=True)
class ModelResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ModelPort(Protocol):
    def generate(self, prompt: str) -> ModelResponse: ...


# These contracts keep provider transport details outside the application.


class RequirementSourcePort(Protocol):
    def read(self, reference: SourceReference) -> RequirementInput: ...


class IssuePublisherPort(Protocol):
    capabilities: frozenset[str]

    def publish(self, request: 'PublicationRequest') -> PublicationResult: ...
