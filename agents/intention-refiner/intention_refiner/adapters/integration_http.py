import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from intention_refiner.domain.integration import FailureReason, IntegrationError
from intention_refiner.telemetry import PublicationPayloadMetrics


class CircuitBreaker:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._streak = 0
        self._until: float | None = None
        self._probe = False

    def before_request(self) -> bool:
        with self._lock:
            if self._until is None:
                return False
            if self.clock() < self._until or self._probe:
                raise IntegrationError("circuit_open")
            self._probe = True
            return True

    def after_response(
        self, response: httpx.Response, probe: bool | None = None
    ) -> None:
        with self._lock:
            cooldown = retry_cooldown(response.headers.get("Retry-After"))
            if probe is True or (probe is None and self._probe):
                self._probe = False
                if response.is_success:
                    self._until = None
                    self._streak = 0
                else:
                    self._until = self.clock() + cooldown
                return
            if response.status_code == 429:
                self._streak += 1
                if self._streak >= 5:
                    self._until = self.clock() + cooldown
            else:
                self._streak = 0

    def transport_failure(self, probe: bool | None = None) -> None:
        with self._lock:
            if probe is True or (probe is None and self._probe):
                self._probe = False
                self._until = self.clock() + 60


def retry_cooldown(value: str | None) -> float:
    if value is None:
        return 60
    try:
        if value.isascii() and value.isdigit():
            return max(60, float(value))
        date = parsedate_to_datetime(value)
        return max(60, (date - datetime.now(UTC)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 60


@dataclass(frozen=True)
class HttpRequest:
    method: str
    path: str
    operation: str = "read"
    payload: dict | None = None
    params: dict | None = None
    allow_not_found: bool = False


class IntegrationHttp:
    def __init__(self, dependencies):
        self.dependencies = dependencies

    def send(self, request: HttpRequest) -> httpx.Response:
        deps = self.dependencies
        probe = deps.breaker.before_request()
        config = deps.config
        content = None
        headers = {"Accept": "application/json"}
        auth = None
        base = config.jira_base_url
        auth = httpx.BasicAuth(
            config.jira_email, config.jira_api_token.get_secret_value()
        )
        if request.payload is not None:
            content = json.dumps(
                request.payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
            if deps.telemetry:
                deps.telemetry.record_publication_payload(
                    PublicationPayloadMetrics(
                        config.provider, request.operation, len(content)
                    )
                )
        try:
            response = deps.client.request(
                request.method,
                base + request.path,
                content=content,
                headers=headers,
                auth=auth,
                params=request.params,
                timeout=config.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            deps.breaker.transport_failure(probe)
            raise IntegrationError("timeout", request.operation) from None
        except httpx.HTTPError:
            deps.breaker.transport_failure(probe)
            raise IntegrationError("network", request.operation) from None
        deps.breaker.after_response(response, probe)
        if response.status_code == 404 and request.allow_not_found:
            return response
        if not response.is_success:
            reason = failure_reason(response)
            raise IntegrationError(reason, request.operation)
        return response


def failure_reason(response: httpx.Response) -> FailureReason:
    if response.status_code == 429 or (
        response.status_code == 403
        and (
            "retry-after" in response.headers
            or response.headers.get("x-ratelimit-remaining") == "0"
        )
    ):
        return "rate_limit"
    if response.status_code in (401, 403):
        return "auth"
    return "remote_error"
