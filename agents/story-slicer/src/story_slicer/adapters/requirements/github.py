"""GitHub issue input and story issue publishing over HTTPX."""

import re
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr

from story_slicer.domain.models import Requirement, RequirementDocument, Story
from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import InputError
from story_slicer.ports.requirements import (
    RequirementSource,
    StoryPublishRequest,
    StoryPublishResult,
)

_API_URL = "https://api.github.com"
_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_repository(owner: str, repository: str) -> None:
    if not _OWNER_PATTERN.fullmatch(owner) or not _REPOSITORY_PATTERN.fullmatch(
        repository
    ):
        raise InputError("GitHub reference contains an invalid repository name")


def parse_issue_reference(reference: str) -> tuple[str, str, int]:
    if reference.startswith("https://"):
        parsed = urlparse(reference)
        parts = parsed.path.strip("/").split("/")
        if (
            parsed.hostname != "github.com"
            or parsed.query
            or parsed.fragment
            or len(parts) != 4
            or parts[2] != "issues"
        ):
            raise InputError("GitHub reference must be an issue URL")
        owner, repository, _, number = parts
    else:
        match = re.fullmatch(r"([^/\s#]+)/([^/\s#]+)#([1-9][0-9]*)", reference)
        if match is None:
            raise InputError("GitHub reference must use owner/repo#number")
        owner, repository, number = match.groups()
    _validate_repository(owner, repository.removesuffix(".git"))
    if not number.isdecimal() or int(number) < 1:
        raise InputError("GitHub issue number must be positive")
    return owner, repository.removesuffix(".git"), int(number)


def _project_name(repository: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", repository).strip("-_")
    if not value or not value[0].isalpha():
        value = "GH-" + value
    return value.upper()


def _token(settings: RuntimeSettings) -> str:
    token: SecretStr | None = settings.github_api_token
    if token is None:
        raise InputError("Set STORY_SLICER_GITHUB_TOKEN to use GitHub")
    return token.get_secret_value()


class GitHubRequirementLoader:
    def __init__(self, settings: RuntimeSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def load(self, source: RequirementSource) -> RequirementDocument:
        owner, repository, number = parse_issue_reference(source.reference)
        try:
            response = await self._client.get(
                f"{_API_URL}/repos/{owner}/{repository}/issues/{number}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {_token(self._settings)}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
            issue = response.json()
        except InputError:
            raise
        except httpx.TimeoutException:
            raise InputError("GitHub issue request timed out") from None
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in {401, 403}:
                raise InputError(
                    "GitHub authentication failed; check STORY_SLICER_GITHUB_TOKEN"
                ) from None
            if status == 404:
                raise InputError(
                    "GitHub issue was not found or is not accessible"
                ) from None
            raise InputError(
                f"GitHub returned HTTP {status} while reading issue"
            ) from None
        except httpx.HTTPError, ValueError:
            raise InputError("GitHub issue request failed") from None
        if not isinstance(issue, dict):
            raise InputError("GitHub returned an invalid issue response")
        if "pull_request" in issue:
            raise InputError("GitHub reference points to a pull request, not an issue")
        if issue.get("number") != number:
            raise InputError("GitHub returned a mismatched issue number")
        title = issue.get("title")
        body = issue.get("body")
        title = title.strip() if isinstance(title, str) else ""
        body = body.strip() if isinstance(body, str) else ""
        if not title and not body:
            raise InputError("GitHub issue must have a title or description")
        if len((title + body).encode("utf-8")) > self._settings.max_input_bytes:
            raise InputError("GitHub issue exceeds the configured input size limit")
        html_url = issue.get("html_url")
        if not isinstance(html_url, str) or not html_url.startswith(
            "https://github.com/"
        ):
            raise InputError("GitHub returned an invalid issue URL")
        description = title or body
        context = body if title and body else None
        return RequirementDocument(
            project=_project_name(repository),
            requirements=[Requirement(description=description, context=context)],
        )


def _story_body(story: Story, source_url: str | None) -> str:
    scenarios = "\n\n".join(
        f"### {scenario.Scenario}\n"
        f"**Given** {scenario.Given}\n\n"
        f"**When** {scenario.When}\n\n"
        f"**Then** {scenario.Then}"
        for scenario in story.acceptance_criteria
    )
    source = f"\n\nSource requirement: {source_url}" if source_url else ""
    clarification = (
        ", ".join(story.clarification)
        if isinstance(story.clarification, list)
        else story.clarification or "None"
    )
    suggestions = (
        ", ".join(story.suggestions)
        if isinstance(story.suggestions, list)
        else story.suggestions or "None"
    )
    return (
        f"**As** {story.Who}, I want {story.Action_What}, "
        f"so that {story.Benefit_Why}.\n\n"
        f"**Priority:** {story.Priority}\n\n"
        f"**Tags:** {', '.join(story.tags) if story.tags else 'None'}\n\n"
        f"**Clarification:** {clarification}\n\n"
        f"**Suggestions:** {suggestions}\n\n"
        f"**Acceptance criteria**\n\n{scenarios}{source}"
    )


class GitHubStoryPublisher:
    def __init__(self, settings: RuntimeSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def publish(self, request: StoryPublishRequest) -> StoryPublishResult:
        created: list[str] = []
        failures: list[str] = []
        try:
            token = _token(self._settings)
        except InputError as error:
            return StoryPublishResult(created=[], failures=[f"All stories: {error}"])
        for story in request.batch.stories:
            try:
                response = await self._client.post(
                    f"{_API_URL}/repos/{request.repository}/issues",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={
                        "title": f"[{story.ID}] {story.title}",
                        "body": _story_body(story, request.source_url),
                    },
                    timeout=self._settings.request_timeout_seconds,
                )
                response.raise_for_status()
                issue = response.json()
                url = issue.get("html_url") if isinstance(issue, dict) else None
                if not isinstance(url, str) or not url.startswith(
                    "https://github.com/"
                ):
                    raise ValueError
                created.append(url)
            except httpx.TimeoutException:
                failures.append(f"{story.ID}: GitHub request timed out")
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status in {401, 403}:
                    failures.append(
                        f"{story.ID}: GitHub authentication or permission failed; "
                        "check token access"
                    )
                else:
                    failures.append(f"{story.ID}: GitHub returned HTTP {status}")
            except httpx.HTTPError, ValueError:
                failures.append(f"{story.ID}: GitHub request failed")
        return StoryPublishResult(created=created, failures=failures)
