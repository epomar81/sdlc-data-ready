import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from story_slicer.application.slice_requirement import (
    SliceRequirement,
    SlicingDependencies,
)
from story_slicer.domain.models import RequirementDocument, Story
from story_slicer.ports.configuration import ConfigurationPort, RuntimeSettings
from story_slicer.ports.errors import ValidationExhaustedError
from story_slicer.ports.filesystem import FileReadRequest, FileSystemPort
from story_slicer.ports.llm import GenerationResult, LLMPort, TokenUsage
from story_slicer.ports.observability import (
    CriticalAlert,
    ObservabilityPort,
    OperationalAlert,
    RepairScheduled,
    SchemaFailure,
    SessionCompleted,
    SessionHandle,
)
from story_slicer.ports.requirements import RequirementParserPort
from tests.fixtures import settings_data, story_data


def dependencies() -> SlicingDependencies:
    configuration = Mock(spec=ConfigurationPort)
    configuration.load.return_value = RuntimeSettings.model_validate(settings_data())
    filesystem = AsyncMock(spec=FileSystemPort)
    filesystem.read.return_value = (
        b"project: SHOP\nrequirements:\n  - description: Track orders\n"
    )
    parser = Mock(spec=RequirementParserPort)
    parser.parse.return_value = RequirementDocument.model_validate(
        {"project": "SHOP", "requirements": [{"description": "Track orders"}]}
    )
    observability = Mock(spec=ObservabilityPort)
    observability.start_session.return_value = SessionHandle(session_id="session")
    return SlicingDependencies(
        configuration=configuration,
        filesystem=filesystem,
        parser=parser,
        llm=AsyncMock(spec=LLMPort),
        observability=observability,
    )


def test_valid_first_attempt() -> None:
    ports = dependencies()
    llm = ports.llm
    assert isinstance(llm, AsyncMock)
    # Provisional duplicate IDs must not prevent authoritative application numbering.
    llm.generate.return_value = GenerationResult(
        text=json.dumps({"stories": [story_data(), story_data()]}),
        usage=TokenUsage(input_tokens=10, output_tokens=20),
    )

    batch = asyncio.run(SliceRequirement(ports).execute("product/requirements.yaml"))

    assert [story.ID for story in batch.stories] == ["SHOP-1", "SHOP-2"]
    assert all(isinstance(story, Story) for story in batch.stories)
    assert isinstance(ports.filesystem, AsyncMock)
    ports.filesystem.read.assert_awaited_once_with(
        FileReadRequest(path="product/requirements.yaml", max_bytes=65536)
    )
    assert isinstance(ports.parser, Mock)
    ports.parser.parse.assert_called_once_with(ports.filesystem.read.return_value)
    assert isinstance(ports.configuration, Mock)
    ports.configuration.load.assert_called_once()
    llm.generate.assert_awaited_once()
    request = llm.generate.call_args.args[0]
    assert request.repair_feedback is None
    assert request.requirement == ports.parser.parse.return_value
    assert isinstance(ports.observability, Mock)
    ports.observability.start_session.assert_called_once()
    events = [call.args[0] for call in ports.observability.record.call_args_list]
    completion = events[-1]
    assert isinstance(completion, SessionCompleted)
    assert completion.outcome == "success" and completion.elapsed_seconds >= 0
    assert completion.usage == TokenUsage(input_tokens=10, output_tokens=20)
    assert completion.usage_complete
    assert not any(
        isinstance(event, RepairScheduled | CriticalAlert) for event in events
    )


def test_successful_self_healing() -> None:
    ports = dependencies()
    invalid = story_data() | {"tags": ["MISSING_INFO"]}
    with pytest.raises(ValidationError) as caught:
        Story.model_validate(invalid)
    broken = json.dumps({"stories": [invalid]})
    llm = ports.llm
    assert isinstance(llm, AsyncMock)
    llm.generate.side_effect = [
        GenerationResult(
            text=broken, usage=TokenUsage(input_tokens=10, output_tokens=20)
        ),
        GenerationResult(
            text=json.dumps({"stories": [story_data()]}),
            usage=TokenUsage(input_tokens=5),
        ),
    ]

    batch = asyncio.run(SliceRequirement(ports).execute("requirements.yaml"))

    assert batch.stories[0].ID == "SHOP-1" and llm.generate.await_count == 2
    first, repaired = [call.args[0] for call in llm.generate.call_args_list]
    assert repaired.requirement == first.requirement
    assert repaired.repair_feedback.previous_response == broken
    assert repaired.repair_feedback.diagnostic == str(caught.value)
    assert "Correct the previous response" in repaired.instructions
    assert isinstance(ports.observability, Mock)
    events = [call.args[0] for call in ports.observability.record.call_args_list]
    assert sum(isinstance(event, SchemaFailure) for event in events) == 1
    assert sum(isinstance(event, RepairScheduled) for event in events) == 1
    completion = events[-1]
    assert isinstance(completion, SessionCompleted) and completion.outcome == "success"
    assert completion.usage == TokenUsage(input_tokens=15, output_tokens=20)
    assert not completion.usage_complete
    assert not any(isinstance(event, CriticalAlert) for event in events)


def test_critical_failure_after_retry_exhaustion() -> None:
    ports = dependencies()
    llm = ports.llm
    assert isinstance(llm, AsyncMock)
    llm.generate.return_value = GenerationResult(
        text="not JSON",
        usage=TokenUsage(input_tokens=10, output_tokens=20),
    )

    with pytest.raises(ValidationExhaustedError):
        asyncio.run(SliceRequirement(ports).execute("requirements.yaml"))

    assert llm.generate.await_count == 3
    assert isinstance(ports.observability, Mock)
    events = [call.args[0] for call in ports.observability.record.call_args_list]
    assert sum(isinstance(event, SchemaFailure) for event in events) == 3
    assert sum(isinstance(event, RepairScheduled) for event in events) == 2
    assert sum(isinstance(event, OperationalAlert) for event in events) == 1
    critical = [event for event in events if isinstance(event, CriticalAlert)]
    assert len(critical) == 1 and critical[0].attempts == 3
    completion = events[-1]
    assert isinstance(completion, SessionCompleted) and completion.outcome == "aborted"
    assert completion.usage == TokenUsage(input_tokens=30, output_tokens=60)
    assert completion.usage_complete
    repair = llm.generate.call_args_list[1].args[0].repair_feedback
    assert repair.previous_response == "not JSON"
    assert "line 1 column 1" in repair.diagnostic


@pytest.mark.parametrize("limit", ["request", "session"])
def test_timeout_reports_the_exceeded_limit(limit: str) -> None:
    from story_slicer.ports.errors import SessionTimeoutError

    ports = dependencies()
    assert isinstance(ports.configuration, Mock)
    ports.configuration.load.return_value = RuntimeSettings.model_validate(
        settings_data()
        | {
            "request_timeout_seconds": 0.01 if limit == "request" else 1.0,
            "session_timeout_seconds": 0.01 if limit == "session" else 1.0,
        }
    )

    async def slow_generate(request: object) -> GenerationResult:
        await asyncio.sleep(1)
        return GenerationResult(text="{}", usage=TokenUsage())

    assert isinstance(ports.llm, AsyncMock)
    ports.llm.generate.side_effect = slow_generate
    with pytest.raises(SessionTimeoutError) as caught:
        asyncio.run(SliceRequirement(ports).execute("requirements.yaml"))
    assert f"{limit} timeout" in str(caught.value)
    assert "0.01" in str(caught.value)
    assert f"STORY_SLICER_{limit.upper()}_TIMEOUT_SECONDS" in str(caught.value)
    assert ports.llm.generate.await_count == 1
