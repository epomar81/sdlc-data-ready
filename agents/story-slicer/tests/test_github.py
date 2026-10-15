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
from tests.fixtures import settings_data, story_batch_data, story_data


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
        clarification_comment = (
            "MISSING_INFO: Confirm status refresh interval. Show last updated time."
        )
        batch = StoryBatch.model_validate(
            story_batch_data()
            | {
                "stories": [
                    story_data()
                    | {
                        "clarification_comment": clarification_comment,
                        "tags": ["MISSING_INFO"],
                        "labels": ["needs-clarification"],
                    }
                ]
            }
        )

        async def respond(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            if request.url.path == "/repos/octo/shop/issues":
                assert payload["title"] == "[SHOP-1] Track an order"
                assert "Acceptance criteria" in payload["body"]
                assert "Confirm status refresh interval" not in payload["body"]
                assert "MISSING_INFO" not in payload["body"]
                assert "https://github.com/octo/shop/issues/12" in payload["body"]
                return httpx.Response(
                    201,
                    json={
                        "number": 99,
                        "html_url": "https://github.com/octo/shop/issues/99",
                    },
                )
            if request.url.path == "/repos/octo/shop/issues/99/labels":
                assert payload == {"labels": ["needs-clarification", "priority:high"]}
                return httpx.Response(200, json=[])
            assert request.url.path == "/repos/octo/shop/issues/99/comments"
            assert payload == {"body": clarification_comment}
            return httpx.Response(201, json={"id": 1})

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
        batch_data = story_batch_data()
        batch = StoryBatch.model_validate(
            batch_data
            | {
                "stories": [story_data(), story_data() | {"ID": "SHOP-2"}],
                "story_count": 2,
            }
        )
        attempts = 0

        def respond(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if request.url.path.endswith("/issues"):
                if request.content and b"SHOP-1" in request.content:
                    return httpx.Response(
                        201,
                        json={
                            "number": 100,
                            "html_url": "https://github.com/octo/shop/issues/100",
                        },
                    )
                return httpx.Response(
                    201,
                    json={
                        "number": 101,
                        "html_url": "https://github.com/octo/shop/issues/101",
                    },
                )
            if request.url.path.endswith("/100/labels"):
                return httpx.Response(422, text="github-secret")
            if request.url.path.endswith("/comments"):
                return httpx.Response(201, json={"id": 2})
            return httpx.Response(200, json=[])

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await GitHubStoryPublisher(github_settings(), client).publish(
                StoryPublishRequest(batch=batch, repository="octo/shop")
            )
        assert result.created == [
            "https://github.com/octo/shop/issues/100",
            "https://github.com/octo/shop/issues/101",
        ]
        assert result.failures == ["SHOP-1: GitHub labels returned HTTP 422"]

    asyncio.run(run())


def test_story_publisher_preserves_issue_when_comment_creation_fails() -> None:
    async def run() -> None:
        story = story_data() | {
            "tags": ["MISSING_INFO"],
            "labels": ["needs-clarification"],
            "clarification_comment": "MISSING_INFO: Confirm delivery window.",
        }
        batch = StoryBatch.model_validate(story_batch_data() | {"stories": [story]})

        def respond(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/issues"):
                return httpx.Response(
                    201,
                    json={
                        "number": 42,
                        "html_url": "https://github.com/octo/shop/issues/42",
                    },
                )
            if request.url.path.endswith("/labels"):
                return httpx.Response(200, json=[])
            return httpx.Response(503, text="github-secret")

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await GitHubStoryPublisher(github_settings(), client).publish(
                StoryPublishRequest(batch=batch, repository="octo/shop")
            )
        assert result.created == ["https://github.com/octo/shop/issues/42"]
        assert result.failures == ["SHOP-1: GitHub comment returned HTTP 503"]

    asyncio.run(run())
