import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from orchestrator.infrastructure.inbound.app import create_app


class Dispatcher:
    def __init__(self) -> None:
        self.events = []

    async def execute(self, event) -> None:
        self.events.append(event)


def payload(action: str = "opened", labels: list[str] | None = None) -> dict:
    value = {
        "action": action,
        "issue": {
            "number": 12,
            "title": "Improve search",
            "body": "Search should support filters.",
            "html_url": "https://github.com/acme/app/issues/12",
            "labels": [{"id": 1, "name": name} for name in labels or []],
        },
        "repository": {"full_name": "acme/app"},
        "sender": {"login": "developer"},
    }
    if action == "labeled":
        value["label"] = {"id": 2, "name": "ready-for-slicing"}
    return value


def signed_headers(body: bytes, event_name: str = "issues") -> dict[str, str]:
    digest = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Event": event_name,
        "X-GitHub-Delivery": "delivery-123",
        "Content-Type": "application/json",
    }


def test_opened_webhook_acknowledges_and_dispatches() -> None:
    dispatcher = Dispatcher()
    with TestClient(create_app(dispatcher, "test-secret")) as client:
        body = json.dumps(payload()).encode()
        response = client.post(
            "/webhooks/github", content=body, headers=signed_headers(body)
        )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert len(dispatcher.events) == 1
    assert dispatcher.events[0].issue_reference == "acme/app#12"


def test_labeled_webhook_dispatches_slicer_event() -> None:
    dispatcher = Dispatcher()
    with TestClient(create_app(dispatcher, "test-secret")) as client:
        body = json.dumps(payload("labeled")).encode()
        response = client.post(
            "/webhooks/github", content=body, headers=signed_headers(body)
        )

    assert response.status_code == 200
    assert dispatcher.events[0].label.name == "ready-for-slicing"


def test_opened_issue_with_ready_label_is_acknowledged_without_dispatch() -> None:
    dispatcher = Dispatcher()
    with TestClient(create_app(dispatcher, "test-secret")) as client:
        body = json.dumps(payload(labels=["ready-for-slicing"])).encode()
        response = client.post(
            "/webhooks/github", content=body, headers=signed_headers(body)
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert dispatcher.events == []


def test_invalid_signature_is_rejected() -> None:
    with TestClient(create_app(Dispatcher(), "test-secret")) as client:
        response = client.post(
            "/webhooks/github",
            content=b"{}",
            headers={
                "X-Hub-Signature-256": "sha256=bad",
                "X-GitHub-Event": "issues",
            },
        )
    assert response.status_code == 401


def test_missing_issue_fields_are_rejected() -> None:
    with TestClient(create_app(Dispatcher(), "test-secret")) as client:
        body = json.dumps({"action": "opened"}).encode()
        response = client.post(
            "/webhooks/github", content=body, headers=signed_headers(body)
        )
    assert response.status_code == 422


def test_non_issue_event_is_acknowledged_without_dispatch() -> None:
    dispatcher = Dispatcher()
    with TestClient(create_app(dispatcher, "test-secret")) as client:
        body = b"{}"
        response = client.post(
            "/webhooks/github",
            content=body,
            headers=signed_headers(body, "push"),
        )
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert dispatcher.events == []
