"""Load and parse bounded local YAML requirement files."""

import asyncio
from dataclasses import dataclass

from story_slicer.domain.models import RequirementDocument
from story_slicer.ports.errors import SessionTimeoutError
from story_slicer.ports.filesystem import FileReadRequest, FileSystemPort
from story_slicer.ports.requirements import RequirementParserPort, RequirementSource


@dataclass(frozen=True, slots=True)
class YamlLoaderDependencies:
    filesystem: FileSystemPort
    parser: RequirementParserPort
    max_bytes: int
    timeout_seconds: float


class YamlRequirementLoader:
    def __init__(self, dependencies: YamlLoaderDependencies) -> None:
        self._dependencies = dependencies

    async def load(self, source: RequirementSource) -> RequirementDocument:
        try:
            content = await asyncio.wait_for(
                self._dependencies.filesystem.read(
                    FileReadRequest(
                        path=source.reference,
                        max_bytes=self._dependencies.max_bytes,
                    )
                ),
                timeout=self._dependencies.timeout_seconds,
            )
        except TimeoutError:
            raise SessionTimeoutError("Requirement file read timed out") from None
        return self._dependencies.parser.parse(content)
