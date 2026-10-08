import json
from datetime import UTC

import httpx
import pytest
from pydantic import ValidationError

from intention_refiner.adapters.requirements.github import GitHubAdapter
from intention_refiner.adapters.requirements.integration_http import (
    CircuitBreaker,
    IntegrationError,
)
from intention_refiner.adapters.requirements.integrations import (
    AdapterDependencies,
    JiraAdapter,
)
from intention_refiner.adapters.requirements.rich_text import adf_to_text
from intention_refiner.application.integrations import (
    LoadRequirement,
    PublicationRequest,
    PublishRequirement,
    SourceReference,
)
from intention_refiner.config import IntegrationConfig, LabelPolicy
from intention_refiner.domain.integration import PublicationResult


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def test_circuit_opens_after_five_429_and_recovers():
    clock = Clock()
    breaker = CircuitBreaker(clock)
    for _ in range(5):
        breaker.before_request()
        breaker.after_response(httpx.Response(429))
    with pytest.raises(IntegrationError, match="circuit_open"):
        breaker.before_request()
    clock.now = 60
    breaker.before_request()
    with pytest.raises(IntegrationError):
        breaker.before_request()
    breaker.after_response(httpx.Response(200))
    breaker.before_request()


def test_circuit_resets_streak_and_honors_retry_after():
    clock = Clock()
    breaker = CircuitBreaker(clock)
    for _ in range(4):
        breaker.before_request()
        breaker.after_response(httpx.Response(429))
    breaker.before_request()
    breaker.after_response(httpx.Response(403))
    for _ in range(5):
        breaker.before_request()
        breaker.after_response(httpx.Response(429, headers={"Retry-After": "120"}))
    clock.now = 60
    with pytest.raises(IntegrationError):
        breaker.before_request()
    clock.now = 120
    breaker.before_request()
    breaker.after_response(httpx.Response(500))
    with pytest.raises(IntegrationError):
        breaker.before_request()


def test_publication_result_is_strict_and_frozen():
    with pytest.raises(ValidationError):
        PublicationResult(
            provider="github",
            identifier="a/b#1",
            result_comment_id="12",
            completed_operations=["result"],
        )
    result = PublicationResult(
        provider="github",
        identifier="a/b#1",
        result_comment_id=12,
        completed_operations=("result",),
    )
    with pytest.raises(ValidationError):
        result.result_comment_id = 13
    with pytest.raises(ValidationError):
        PublicationResult(
            provider="jira",
            identifier="A-1",
            result_comment_id=12,
            completed_operations=("result",),
        )


def test_adf_preserves_readable_structure():
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "hardBreak"},
                    {"type": "mention", "attrs": {"text": "@Jane"}},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Item"}],
                            }
                        ],
                    }
                ],
            },
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "Cell"}],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    text = adf_to_text(document)
    assert "Hello\n@Jane" in text
    assert "- Item" in text
    assert "Cell" in text
    with pytest.raises(TypeError):
        adf_to_text({"type": "doc", "content": "invalid"})


class RecordingTelemetry:
    def __init__(self):
        self.outcomes = []
        self.payloads = []

    def record_publication(self, event):
        self.outcomes.append(event)

    def record_publication_payload(self, event):
        self.payloads.append(event)

    def span(self, name, attributes):
        from contextlib import nullcontext

        return nullcontext(None)


def github_dependencies(handler):
    config = IntegrationConfig(provider="github", github_token="secret")
    return AdapterDependencies(
        config=config,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        breaker=CircuitBreaker(),
    )


def test_github_source_normalizes_and_rejects_pull_request():
    responses = [
        {"id": 1, "number": 12, "title": "Build café", "body": None},
        {"id": 1, "number": 12, "title": "PR", "body": "", "pull_request": {}},
    ]

    def handler(request):
        assert request.url.path == "/repos/acme/app/issues/12"
        return httpx.Response(200, json=responses.pop(0))

    adapter = GitHubAdapter(github_dependencies(handler))
    requirement = LoadRequirement(adapter).execute(
        SourceReference(
            provider="github", reference="https://github.com/acme/app/issues/12"
        )
    )
    assert "Build café" in requirement.text
    assert requirement.provenance.identifier == "acme/app#12"
    with pytest.raises(IntegrationError):
        adapter.read(SourceReference(provider="github", reference="acme/app#12"))


def test_remote_contract_failure_is_sanitized():
    adapter = GitHubAdapter(
        github_dependencies(
            lambda request: httpx.Response(
                200, json={"id": "secret", "number": 1, "title": "private"}
            )
        )
    )
    with pytest.raises(IntegrationError) as error:
        adapter.read(SourceReference(provider="github", reference="a/b#1"))
    assert error.value.reason == "validation"
    assert "private" not in str(error.value)
    assert "secret" not in str(error.value)


def test_file_source_stays_plain_text(tmp_path):
    from intention_refiner.adapters.filesystem.files import TextFileReader

    source = tmp_path / "idea.txt"
    source.write_text("Idea", encoding="utf-8")
    result = LoadRequirement(TextFileReader()).execute(
        SourceReference(provider="file", reference=str(source))
    )
    assert result.text == "Idea"
    assert result.provenance is None


def test_label_policy_project_overrides(tmp_path):
    path = tmp_path / "integrations.yaml"
    path.write_text(
        "github:\n  defaults:\n    ai_review: needs-review\n  projects:\n    acme/app:\n      clarification: needs-answer\n"
    )
    config = IntegrationConfig(provider="github", github_token="secret")
    policy = LabelPolicy.load(path).for_source(
        SourceReference(provider="github", reference="acme/app#1")
    )
    assert policy.clarification == "needs-answer"
    assert policy.ai_review == "needs-review"
    assert config.timeout_seconds == 30


def sample_report():
    from intention_refiner.domain.models import RefinementReport

    return RefinementReport(
        provider="gemini",
        model="example",
        response_time_ms=1,
        initiative={"title": "Café"},
        suggestions=[
            {"field_name": "target", "tag": "CLARIFICATION", "text": "Who uses it?"},
            {
                "field_name": "target",
                "tag": "MISSING_INFO",
                "text": "Consider customers.",
            },
        ],
        audit={
            "ambiguities": [],
            "missing_information": [],
            "metric_gaps": [],
            "other_risks": [],
        },
        refinement_proposals=[],
    )


def test_github_publication_comments_labels_metrics_and_rerun():
    comments = []
    labels = []
    writes = []

    def handler(request):
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        if path == "/user":
            return httpx.Response(200, json={"id": 7})
        if request.method == "GET" and path.endswith("/comments"):
            return httpx.Response(200, json=comments)
        if request.method == "POST" and path.endswith("/comments"):
            comment = {"id": len(comments) + 1, "body": body["body"], "user": {"id": 7}}
            comments.append(comment)
            writes.append(request)
            return httpx.Response(201, json=comment)
        if request.method == "PATCH":
            comment = next(
                item for item in comments if str(item["id"]) == path.rsplit("/", 1)[1]
            )
            comment["body"] = body["body"]
            return httpx.Response(200, json=comment)
        if "/labels/" in path:
            return httpx.Response(404)
        if path == "/repos/acme/app/labels":
            return httpx.Response(201, json={"name": body["name"]})
        if path.endswith("/labels"):
            if request.method == "POST":
                labels.extend(body["labels"])
                writes.append(request)
            return httpx.Response(200, json=[{"name": name} for name in labels])
        raise AssertionError(str(request.url))

    telemetry = RecordingTelemetry()
    deps = github_dependencies(handler)
    deps.telemetry = telemetry
    adapter = GitHubAdapter(deps)
    request = PublicationRequest(
        source=SourceReference(provider="github", reference="acme/app#1"),
        report=sample_report(),
        labels=LabelPolicy().for_source(
            SourceReference(provider="github", reference="acme/app#1")
        ),
    )
    use_case = PublishRequirement(adapter, telemetry)
    result = use_case.execute(request)
    assert result.result_comment_id == 1
    assert result.clarification_comment_id == 2
    assert labels == ["question"]
    assert "MISSING_INFO" in comments[0]["body"]
    assert "Consider customers" not in comments[1]["body"]
    use_case.execute(request)
    assert len(comments) == 2
    assert len(telemetry.outcomes) == 2
    assert all(event.succeeded for event in telemetry.outcomes)
    assert telemetry.payloads[0].size_bytes == len(writes[0].content)


def test_jira_source_and_publication_204_labels():
    comments = []
    applied = []

    def handler(request):
        path = request.url.path
        if path.endswith("/myself"):
            return httpx.Response(200, json={"accountId": "agent"})
        if path.endswith("/comment"):
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "comments": comments,
                        "total": len(comments),
                        "startAt": 0,
                        "maxResults": 100,
                    },
                )
            body = json.loads(request.content)["body"]
            comment = {
                "id": str(len(comments) + 1),
                "body": body,
                "author": {"accountId": "agent"},
            }
            comments.append(comment)
            return httpx.Response(201, json=comment)
        if request.method == "PUT":
            applied.extend(
                item["add"] for item in json.loads(request.content)["update"]["labels"]
            )
            return httpx.Response(204)
        return httpx.Response(
            200,
            json={
                "id": "42",
                "key": "TEAM-1",
                "fields": {
                    "summary": "Idea",
                    "description": None,
                    "labels": ["existing", *applied],
                },
            },
        )

    config = IntegrationConfig(
        provider="jira",
        jira_base_url="https://example.atlassian.net",
        jira_email="agent@example.com",
        jira_api_token="secret",
    )
    adapter = JiraAdapter(
        AdapterDependencies(
            config=config,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            breaker=CircuitBreaker(),
        )
    )
    source = SourceReference(provider="jira", reference="TEAM-1")
    assert "Idea" in adapter.read(source).text
    result = adapter.publish(
        PublicationRequest(
            source=source,
            report=sample_report(),
            labels=LabelPolicy().for_source(source),
        )
    )
    assert result.result_comment_id == "1"
    assert applied == ["question"]


def test_publication_partial_failure_counts_once():
    def handler(request):
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 7})
        if request.method == "GET":
            return httpx.Response(200, json=[])
        if b"intention-refiner:clarification" in request.content:
            return httpx.Response(429)
        return httpx.Response(
            201,
            json={
                "id": 1,
                "body": json.loads(request.content)["body"],
                "user": {"id": 7},
            },
        )

    telemetry = RecordingTelemetry()
    adapter = GitHubAdapter(github_dependencies(handler))
    source = SourceReference("github", "acme/app#1")
    request = PublicationRequest(
        source, sample_report(), LabelPolicy().for_source(source)
    )
    with pytest.raises(IntegrationError) as error:
        PublishRequirement(adapter, telemetry).execute(request)
    assert error.value.completed_operations == ("result",)
    assert error.value.uncertain_operation == "clarification"
    assert len(telemetry.outcomes) == 1
    assert telemetry.outcomes[0].reason == "rate_limit"


@pytest.mark.parametrize(
    "status,reason",
    [(401, "auth"), (403, "auth"), (429, "rate_limit"), (500, "remote_error")],
)
def test_http_failure_classification(status, reason):
    adapter = GitHubAdapter(github_dependencies(lambda request: httpx.Response(status)))
    with pytest.raises(IntegrationError) as error:
        adapter.read(SourceReference("github", "acme/app#1"))
    assert error.value.reason == reason


def test_transport_failure_half_open_reopens_and_isolates_providers():
    clock = Clock()
    breaker = CircuitBreaker(clock)
    for _ in range(5):
        breaker.before_request()
        breaker.after_response(httpx.Response(429))
    CircuitBreaker(clock).before_request()
    clock.now = 60
    breaker.before_request()
    breaker.transport_failure()
    with pytest.raises(IntegrationError):
        breaker.before_request()


def test_unknown_adf_containers_and_links():
    document = {
        "type": "futureContainer",
        "content": [
            {
                "type": "text",
                "text": "Docs",
                "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}],
            }
        ],
    }
    assert adf_to_text(document) == "Docs (https://example.com)"


def test_github_comment_pagination():
    def handler(request):
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(
            200,
            headers={
                "Link": '<https://api.github.com/repos/a/b/issues/1/comments?page=2>; rel="next"'
            }
            if page == 1
            else {},
            json=[
                {"id": number, "body": "human", "user": {"id": 9}}
                for number in (range(1, 101) if page == 1 else [101])
            ],
        )

    adapter = GitHubAdapter(github_dependencies(handler))
    assert len(adapter.comments(SourceReference("github", "a/b#1"))) == 101


def test_oversize_publication_fails_before_http():
    def handler(request):
        raise AssertionError("No HTTP requests allowed")

    report = sample_report()
    report.initiative.problem_statement = "x" * 65536
    source = SourceReference("github", "a/b#1")
    with pytest.raises(IntegrationError, match="payload size"):
        GitHubAdapter(github_dependencies(handler)).publish(
            PublicationRequest(source, report, LabelPolicy().for_source(source))
        )


def test_invalid_remote_id_after_result_reports_partial_progress():
    def handler(request):
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 7})
        if request.method == "GET":
            return httpx.Response(200, json=[])
        body = json.loads(request.content)["body"]
        identifier = "private-value" if "clarification:v1" in body else 1
        return httpx.Response(
            201, json={"id": identifier, "body": body, "user": {"id": 7}}
        )

    telemetry = RecordingTelemetry()
    source = SourceReference("github", "a/b#1")
    with pytest.raises(IntegrationError) as error:
        PublishRequirement(
            GitHubAdapter(github_dependencies(handler)), telemetry
        ).execute(
            PublicationRequest(
                source, sample_report(), LabelPolicy().for_source(source)
            )
        )
    assert error.value.reason == "validation"
    assert error.value.completed_operations == ("result",)
    assert "private-value" not in str(error.value)
    assert telemetry.outcomes[0].reason == "validation"


def test_github_reconciles_questions_preserving_human_comments_and_labels():
    comments = [
        {
            "id": 1,
            "body": "[intention-refiner:result:v1]\nHuman copy",
            "user": {"id": 8},
        },
        {
            "id": 2,
            "body": "[intention-refiner:result:v1]\nOld result",
            "user": {"id": 7},
        },
        {
            "id": 3,
            "body": "[intention-refiner:clarification:v1]\nOld questions",
            "user": {"id": 7},
        },
    ]
    labels = ["bug"]

    def handler(request):
        path = request.url.path
        if path == "/user":
            return httpx.Response(200, json={"id": 7})
        if path.endswith("/comments"):
            return httpx.Response(200, json=comments)
        if request.method == "PATCH":
            comment = next(
                item for item in comments if str(item["id"]) == path.rsplit("/", 1)[1]
            )
            comment["body"] = json.loads(request.content)["body"]
            return httpx.Response(200, json=comment)
        if "/labels/" in path:
            return httpx.Response(200, json={"name": "help wanted"})
        if path.endswith("/labels"):
            if request.method == "POST":
                labels.extend(json.loads(request.content)["labels"])
            return httpx.Response(200, json=[{"name": name} for name in labels])
        raise AssertionError(str(request.url))

    source = SourceReference("github", "a/b#1")
    report = sample_report()
    report.suggestions[0].tag = "AI_ENHANCED"
    result = GitHubAdapter(github_dependencies(handler)).publish(
        PublicationRequest(source, report, LabelPolicy().for_source(source))
    )
    assert result.result_comment_id == 2
    assert result.clarification_comment_id == 3
    assert "resolved" in comments[2]["body"]
    assert comments[0]["body"].endswith("Human copy")
    assert labels == ["bug", "help wanted"]


@pytest.mark.parametrize(
    "error_type,reason",
    [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "network")],
)
def test_transport_errors_are_sanitized(error_type, reason):
    def handler(request):
        raise error_type("private request details", request=request)

    with pytest.raises(IntegrationError) as error:
        GitHubAdapter(github_dependencies(handler)).read(
            SourceReference("github", "a/b#1")
        )
    assert error.value.reason == reason
    assert "private" not in str(error.value)


def test_retry_after_http_date_and_invalid_value():
    from datetime import datetime, timedelta
    from email.utils import format_datetime

    from intention_refiner.adapters.requirements.integration_http import retry_cooldown

    assert retry_cooldown("invalid") == 60
    assert retry_cooldown("-1") == 60
    assert (
        retry_cooldown(format_datetime(datetime.now(UTC) + timedelta(seconds=130)))
        > 120
    )


def test_jira_malformed_adf_is_sanitized():
    config = IntegrationConfig(
        provider="jira",
        jira_base_url="https://example.atlassian.net",
        jira_email="a@example.com",
        jira_api_token="secret",
    )

    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": "1",
                "key": "A-1",
                "fields": {
                    "summary": "Private",
                    "description": {"type": "doc", "content": "secret"},
                },
            },
        )

    adapter = JiraAdapter(
        AdapterDependencies(
            config,
            httpx.Client(transport=httpx.MockTransport(handler)),
            CircuitBreaker(),
        )
    )
    with pytest.raises(IntegrationError, match="validation") as error:
        adapter.read(SourceReference("jira", "A-1"))
    assert "secret" not in str(error.value)


def test_unsupported_publisher_is_counted_without_writes():
    from unittest.mock import MagicMock

    publisher = MagicMock()
    publisher.capabilities = frozenset({"comments"})
    telemetry = RecordingTelemetry()
    source = SourceReference("github", "a/b#1")
    with pytest.raises(IntegrationError, match="unsupported"):
        PublishRequirement(publisher, telemetry).execute(
            PublicationRequest(
                source, sample_report(), LabelPolicy().for_source(source)
            )
        )
    publisher.publish.assert_not_called()
    assert telemetry.outcomes[0].reason == "unsupported"


def test_port_validation_failure_is_counted_and_sanitized():
    class InvalidPublisher:
        capabilities = frozenset({"comments", "labels"})

        def publish(self, request):
            return PublicationResult(
                provider="github",
                identifier="a/b#1",
                result_comment_id="private",
                completed_operations=("result",),
            )

    telemetry = RecordingTelemetry()
    source = SourceReference("github", "a/b#1")
    with pytest.raises(IntegrationError, match="validation"):
        PublishRequirement(InvalidPublisher(), telemetry).execute(
            PublicationRequest(
                source, sample_report(), LabelPolicy().for_source(source)
            )
        )
    assert len(telemetry.outcomes) == 1
    assert telemetry.outcomes[0].reason == "validation"


def test_late_response_cannot_complete_another_requests_probe():
    clock = Clock()
    breaker = CircuitBreaker(clock)
    ordinary = breaker.before_request()
    for _ in range(5):
        ticket = breaker.before_request()
        breaker.after_response(httpx.Response(429), ticket)
    clock.now = 60
    probe = breaker.before_request()
    breaker.after_response(httpx.Response(200), ordinary)
    with pytest.raises(IntegrationError):
        breaker.before_request()
    breaker.after_response(httpx.Response(200), probe)
    breaker.before_request()


def test_publication_result_validates_issue_identity_and_operations():
    with pytest.raises(ValidationError):
        PublicationResult(
            provider="github",
            identifier="arbitrary",
            result_comment_id=1,
            completed_operations=("result",),
        )
    with pytest.raises(ValidationError):
        PublicationResult(
            provider="jira",
            identifier="A-1",
            result_comment_id="1",
            clarification_comment_id="2",
            completed_operations=("result",),
        )


def test_adf_rejects_null_children():
    with pytest.raises(TypeError):
        adf_to_text({"type": "doc", "version": 1, "content": [None]})
