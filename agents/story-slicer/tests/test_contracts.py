import asyncio

import pytest
from pydantic import ValidationError

from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.filesystem import FileReadRequest, FileSystemPort
from story_slicer.ports.llm import TokenUsage
from story_slicer.ports.requirements import RequirementSource
from tests.fixtures import settings_data


def test_usage_distinguishes_unknown_from_zero() -> None:
    assert TokenUsage().input_tokens is None
    assert TokenUsage(input_tokens=0, output_tokens=1).input_tokens == 0
    with pytest.raises(ValidationError):
        TokenUsage(input_tokens=-1)


def test_settings_are_immutable_and_mask_secrets() -> None:
    settings = RuntimeSettings.model_validate(settings_data())
    assert "test-credential" not in settings.model_dump_json()
    with pytest.raises(ValidationError):
        settings.max_retries = 3  # type: ignore[misc]


class FakeFileSystem:
    async def read(self, request: FileReadRequest) -> bytes:
        return request.path.encode()


def test_file_path_contract_and_port() -> None:
    source = RequirementSource(path="requirements.yaml")
    request = FileReadRequest(path=source.path, max_bytes=1024)
    filesystem: FileSystemPort = FakeFileSystem()
    assert asyncio.run(filesystem.read(request)) == b"requirements.yaml"
    with pytest.raises(ValidationError):
        RequirementSource(path=" ")
    with pytest.raises(ValidationError):
        FileReadRequest(path=source.path, max_bytes=0)
