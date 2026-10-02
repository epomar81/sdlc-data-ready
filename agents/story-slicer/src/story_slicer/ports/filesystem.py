"""Raw file access boundary, independent of YAML parsing."""

from typing import Protocol

from story_slicer.domain.models import NonBlank
from story_slicer.ports.contracts import ContractModel, PositiveInteger


class FileReadRequest(ContractModel):
    path: NonBlank
    max_bytes: PositiveInteger


class FileSystemPort(Protocol):
    async def read(self, request: FileReadRequest) -> bytes:
        """Read a bounded file or raise InputError; relative paths use the cwd."""
        ...
