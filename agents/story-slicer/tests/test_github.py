import asyncio
import json

import httpx
import pytest

from story_slicer.adapters.requirements.github import (
    GitHubRequirementLoader,
    GitHubStoryPublisher,
    parse_issue_reference,
)
from story_slicer.domain.models import StoryBatch
from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import InputError
from story_slicer.ports.requirements import RequirementSource, StoryPublishRequest
from tests.fixtures import settings_data, story_data


def github_settings() -> RuntimeSettings:
    return RuntimeSettings.model_validate(
        settings_data() | {"github_api_token": "github-secret"}
    )


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("octo/shop#12", ("octo", "shop", 12)),
        (
            "https://github.com/octo/shop/issues/12",
            ("octo", "shop", 12),
        ),
    ],
)
def test_parse_issue_reference(reference: str, expected: tuple[str, str, int]) -> None:
    assert parse_issue_reference(reference) == expected


@pytest.mark.parametrize(
    "reference",
    ["bad reference", "https://github.com/a/b/issues/0", "a/../b#3"],
)
def test_parse_issue_reference_rejects_ambiguous_or_invalid_values(
    reference: str,
) -> None:
    with pytest.raises(InputError):
        parse_issue_reference(reference)


def test_github_requirement_loader_uses_title_and_body() -> None:
    async def run() -> None:
        async def respond(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/repos/octo/shop/issues/12"
            assert request.headers["authorization"] == "Bearer github-secret"
            return httpx.Response(
                200,
                json={
                    "number": 12,
                    "title": "Track orders",
                    "body": "Customers need delivery updates.",
                    "html_url": "https://github.com/octo/shop/issues/12",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            loader = GitHubRequirementLoader(github_settings(), client)
            result = await loader.load(
                RequirementSource(kind="github", reference="octo/shop#12")
            )
            assert result.project == "SHOP"
            assert result.requirements[0].description == "Track orders"
            assert result.requirements[0].context == "Customers need delivery updates."

    asyncio.run(run())


@pytest.mark.parametrize(
    "issue",
    [
        {"number": 12, "title": "Pull", "body": "body", "pull_request": {}},
        {"number": 13, "title": "Mismatch", "body": "body"},
        {"number": 12, "title": " ", "body": " "},
    ],
)
def test_github_requirement_loader_rejects_invalid_issues(
    issue: dict[str, object],
) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=issue)
            )
        ) as client:
            loader = GitHubRequirementLoader(github_settings(), client)
            with pytest.raises(InputError):
                await loader.load(
                    RequirementSource(kind="github", reference="octo/shop#12")
                )

    asyncio.run(run())


def test_github_loader_sanitizes_http_errors() -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="github-secret")
            )
        ) as client:
            loader = GitHubRequirementLoader(github_settings(), client)
            with pytest.raises(InputError) as caught:
                await loader.load(
                    RequirementSource(kind="github", reference="octo/shop#12")
                )
            assert "github-secret" not in str(caught.value)

    asyncio.run(run())


def test_story_publisher_formats_story_and_reports_created_url() -> None:
    async def run() -> None:
        batch = StoryBatch.model_validate(
            {
                "stories": [
                    story_data()
                    | {
                        "clarification": "Confirm status refresh interval",
                        "suggestions": ["Show last updated time"],
                    }
                ]
            }
        )

        def respond(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert request.url.path == "/repos/octo/shop/issues"
            assert payload["title"] == "[SHOP-1] Track an order"
            assert "Acceptance criteria" in payload["body"]
            assert "Confirm status refresh interval" in payload["body"]
            assert "Show last updated time" in payload["body"]
            assert "https://github.com/octo/shop/issues/12" in payload["body"]
            return httpx.Response(
                201,
                json={"html_url": "https://github.com/octo/shop/issues/99"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await GitHubStoryPublisher(github_settings(), client).publish(
                StoryPublishRequest(
                    batch=batch,
                    repository="octo/shop",
                    source_url="https://github.com/octo/shop/issues/12",
                )
            )
            assert result.created == ["https://github.com/octo/shop/issues/99"]
            assert result.failures == []

    asyncio.run(run())


def test_story_publisher_continues_after_partial_failure() -> None:
    async def run() -> None:
        batch = StoryBatch.model_validate(
            {"stories": [story_data(), story_data() | {"ID": "SHOP-2"}]}
        )
        attempts = 0

        def respond(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(422, text="github-secret")
            return httpx.Response(
                201,
                json={"html_url": "https://github.com/octo/shop/issues/100"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await GitHubStoryPublisher(github_settings(), client).publish(
                StoryPublishRequest(batch=batch, repository="octo/shop")
            )
        assert result.created == ["https://github.com/octo/shop/issues/100"]
        assert result.failures == ["SHOP-1: GitHub returned HTTP 422"]

    asyncio.run(run())
