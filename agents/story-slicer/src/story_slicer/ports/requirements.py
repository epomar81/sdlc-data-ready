"""Requirement source boundary; no YAML or filesystem dependency."""

from typing import Protocol

from story_slicer.domain.models import NonBlank, RequirementDocument
from story_slicer.ports.contracts import ContractModel


class RequirementSource(ContractModel):
    path: NonBlank


class RequirementInputPort(Protocol):
    async def load(self, source: RequirementSource) -> RequirementDocument:
        """Read product data or raise InputError."""
        ...


class RequirementParserPort(Protocol):
    def parse(self, content: bytes) -> RequirementDocument:
        """Decode product data or raise InputError, independently of file access."""
        ...
