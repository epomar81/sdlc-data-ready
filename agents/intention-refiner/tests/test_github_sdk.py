from unittest.mock import patch

import httpx
import pytest

from intention_refiner.adapters.github import GitHubAdapter
from intention_refiner.adapters.integration_http import CircuitBreaker
from intention_refiner.adapters.integrations import AdapterDependencies
from intention_refiner.config import IntegrationConfig
from intention_refiner.domain.integration import SourceReference


@pytest.mark.parametrize(
    "case",
    [
        (401, "invalid, expired, or revoked"),
        (403, "Issues: Read"),
        (403, "Issues: Write"),
    ],
)
def test_sdk_authentication_errors_are_actionable_and_private(case):
    from intention_refiner.domain.integration import IntegrationError

    status, guidance = case
    dependencies = AdapterDependencies(
        IntegrationConfig(provider="github", github_token="private-token"),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    status,
                    json={"message": "private-response"},
                    headers={"X-GitHub-SSO": "private-header"},
                )
            )
        ),
        CircuitBreaker(),
    )
    with pytest.raises(IntegrationError) as error:
        GitHubAdapter(dependencies).read(SourceReference("github", "acme/app#1"))
    assert error.value.reason == "auth"
    message = str(error.value)
    assert f"HTTP {status}" in message
    assert "INTENTION_REFINER_GITHUB_TOKEN" in message
    assert guidance in message
    assert "private-token" not in message
    assert "private-response" not in message
    assert "private-header" not in message


def test_adapter_uses_sdk_issue_endpoint():
    response = httpx.Response(
        200, json={"id": 1, "number": 12, "title": "Idea", "body": None}
    )
    dependencies = AdapterDependencies(
        IntegrationConfig(provider="github", github_token="secret"),
        httpx.Client(transport=httpx.MockTransport(lambda request: response)),
        CircuitBreaker(),
    )
    with patch("intention_refiner.adapters.github.GitHub") as sdk:
        sdk.return_value.rest.issues.get.return_value.raw_response = response
        adapter = GitHubAdapter(dependencies)
        result = adapter.read(SourceReference("github", "acme/app#12"))
    sdk.return_value.rest.issues.get.assert_called_once_with(
        owner="acme", repo="app", issue_number=12
    )
    assert result.provenance.identifier == "acme/app#12"
    assert sdk.call_args.kwargs["auto_retry"] is False
    assert sdk.call_args.kwargs["follow_redirects"] is False
    assert sdk.call_args.kwargs["http_cache"] is False
    assert sdk.call_args.kwargs["timeout"] == 30


def test_sdk_requests_keep_metrics_and_circuit_breaker():
    import pytest
    from test_integrations import RecordingTelemetry

    from intention_refiner.domain.integration import IntegrationError

    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "token secret"
        assert request.extensions["timeout"]["read"] == 30
        return httpx.Response(429)

    dependencies = AdapterDependencies(
        IntegrationConfig(provider="github", github_token="secret"),
        httpx.Client(transport=httpx.MockTransport(handler)),
        CircuitBreaker(),
        RecordingTelemetry(),
    )
    adapter = GitHubAdapter(dependencies)
    for _ in range(5):
        with pytest.raises(IntegrationError) as error:
            adapter.read(SourceReference("github", "acme/app#1"))
        assert error.value.reason == "rate_limit"
    with pytest.raises(IntegrationError) as error:
        adapter.read(SourceReference("github", "acme/app#1"))
    assert error.value.reason == "circuit_open"
    assert len(requests) == 5


def test_sdk_rate_limit_with_http_date_is_classified():
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    import pytest

    from intention_refiner.domain.integration import IntegrationError

    dependencies = AdapterDependencies(
        IntegrationConfig(provider="github", github_token="secret"),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    429,
                    headers={
                        "Retry-After": format_datetime(
                            datetime.now(UTC) + timedelta(seconds=120)
                        )
                    },
                )
            )
        ),
        CircuitBreaker(),
    )
    with pytest.raises(IntegrationError) as error:
        GitHubAdapter(dependencies).read(SourceReference("github", "acme/app#1"))
    assert error.value.reason == "rate_limit"


def test_sdk_rejects_redirects_without_following():
    import pytest

    from intention_refiner.domain.integration import IntegrationError

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com"})

    dependencies = AdapterDependencies(
        IntegrationConfig(provider="github", github_token="secret"),
        httpx.Client(transport=httpx.MockTransport(handler)),
        CircuitBreaker(),
    )
    with pytest.raises(IntegrationError):
        GitHubAdapter(dependencies).read(SourceReference("github", "acme/app#1"))
    assert len(requests) == 1
