import asyncio
import sys
from types import ModuleType, SimpleNamespace

import httpx

from orchestrator.domain.events import IssueWebhook
from orchestrator.infrastructure.agents.slicer import GitHubStoryPublisherAdapter


def _package(monkeypatch, name: str) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = []
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _module(monkeypatch, name: str, **attributes: object) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_publisher_adapter_forwards_batch_comments_and_partial_failures(
    monkeypatch,
) -> None:
    for package_name in (
        "story_slicer",
        "story_slicer.adapters",
        "story_slicer.adapters.configuration",
        "story_slicer.adapters.requirements",
        "story_slicer.domain",
        "story_slicer.ports",
    ):
        _package(monkeypatch, package_name)

    class StoryBatch:
        pass

    class EnvironmentConfiguration:
        def load(self) -> object:
            return object()

    class StoryPublishRequest:
        def __init__(self, **values: object) -> None:
            self.__dict__.update(values)

    class Publisher:
        def __init__(self, settings: object, client: object) -> None:
            pass

        async def publish(self, request: StoryPublishRequest) -> object:
            captured.append(request)
            return SimpleNamespace(
                created=["https://github.com/acme/app/issues/20"],
                failures=["APP-1: comment request failed"],
            )

    captured = []
    _module(
        monkeypatch,
        "story_slicer.adapters.configuration.environment",
        EnvironmentConfiguration=EnvironmentConfiguration,
    )
    _module(
        monkeypatch,
        "story_slicer.adapters.requirements.github",
        GitHubStoryPublisher=Publisher,
    )
    _module(
        monkeypatch,
        "story_slicer.domain.models",
        StoryBatch=StoryBatch,
    )
    _module(
        monkeypatch,
        "story_slicer.ports.requirements",
        StoryPublishRequest=StoryPublishRequest,
    )

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: Client())
    batch = StoryBatch()
    batch.stories = [
        SimpleNamespace(clarification_comment="MISSING_INFO Clarify the user role.")
    ]
    issue_event = IssueWebhook.model_validate(
        {
            "action": "labeled",
            "issue": {
                "number": 12,
                "title": "Improve search",
                "body": "Add filters.",
                "html_url": "https://github.com/acme/app/issues/12",
                "labels": [],
            },
            "repository": {"full_name": "acme/app"},
            "label": {"name": "ready-for-slicing"},
        }
    )

    result = asyncio.run(GitHubStoryPublisherAdapter().publish(issue_event, batch))

    assert captured[0].batch is batch
    assert captured[0].repository == "acme/app"
    assert captured[0].source_url == "https://github.com/acme/app/issues/12"
    assert captured[0].batch.stories[0].clarification_comment.startswith(
        "MISSING_INFO"
    )
    assert result.failures == ["APP-1: comment request failed"]
