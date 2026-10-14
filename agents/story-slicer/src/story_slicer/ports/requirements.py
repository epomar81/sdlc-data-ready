"""Requirement source boundary; no YAML or filesystem dependency."""

from typing import Literal, Protocol

from story_slicer.domain.models import NonBlank, RequirementDocument, StoryBatch
from story_slicer.ports.contracts import ContractModel


class RequirementSource(ContractModel):
    kind: Literal["yaml", "github"] = "yaml"
    reference: NonBlank


class RequirementInputPort(Protocol):
    async def load(self, source: RequirementSource) -> RequirementDocument:
        """Read product data or raise InputError."""
        ...


class StoryPublishResult(ContractModel):
    created: list[NonBlank]
    failures: list[NonBlank]


class StoryPublishRequest(ContractModel):
    batch: StoryBatch
    repository: NonBlank
    source_url: NonBlank | None = None


class StoryPublisherPort(Protocol):
    async def publish(self, request: StoryPublishRequest) -> StoryPublishResult:
        """Create one ticket per story and return successful URLs and failures."""
        ...


class RequirementParserPort(Protocol):
    def parse(self, content: bytes) -> RequirementDocument:
        """Decode product data or raise InputError, independently of file access."""
        ...
