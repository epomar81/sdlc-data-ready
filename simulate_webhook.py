#!/usr/bin/env python3
"""Send signed sample issue webhooks to a local orchestrator."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_URL = "http://localhost:8000/webhooks/github"
DUMMY_SECRET = "local-webhook-secret"


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        name, separator, value = stripped.partition("=")
        if not separator or name.strip() != "GITHUB_WEBHOOK_SECRET":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name.strip()] = value
    return values


def _secret() -> str:
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if secret:
        return secret
    secret = _read_dotenv(Path(__file__).resolve().parent / ".env").get(
        "GITHUB_WEBHOOK_SECRET"
    )
    if secret:
        return secret
    print(
        "WARNING: GITHUB_WEBHOOK_SECRET was not found in the environment or root .env. "
        f"Using dummy secret {DUMMY_SECRET!r}; start the server with the same value.",
        file=sys.stderr,
    )
    return DUMMY_SECRET


def _payloads(
    repository_name: str, issue_number: int
) -> tuple[tuple[str, dict[str, object]], ...]:
    issue = {
        "number": issue_number,
        "title": "Simulated local webhook issue",
        "body": "This issue was sent by simulate_webhook.py.",
        "html_url": f"https://github.com/{repository_name}/issues/{issue_number}",
        "labels": [],
    }
    repository = {"full_name": repository_name}
    opened = {"action": "opened", "issue": issue, "repository": repository}

    labeled_issue = {**issue, "labels": [{"name": "ready-for-slicing"}]}
    labeled = {
        "action": "labeled",
        "issue": labeled_issue,
        "repository": repository,
        "label": {"name": "ready-for-slicing"},
    }
    return (("opened", opened), ("labeled", labeled))


def _send(url: str, event_action: str, payload: dict[str, object], secret: str) -> bool:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-Hub-Signature-256": f"sha256={digest}",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            print(f"issues.{event_action}: HTTP {response.status} — {response_body}")
            return 200 <= response.status < 300
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        print(
            f"issues.{event_action}: HTTP {error.code} — {response_body}",
            file=sys.stderr,
        )
    except URLError as error:
        print(
            f"issues.{event_action}: request failed — {error.reason}",
            file=sys.stderr,
        )
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Webhook endpoint URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--repository",
        default="example/local-project",
        help="GitHub repository in owner/repo form",
    )
    parser.add_argument(
        "--issue-number",
        type=int,
        default=9001,
        help="Issue number used in both simulated payloads",
    )
    args = parser.parse_args()
    secret = _secret()
    results = [
        _send(args.url, action, payload, secret)
        for action, payload in _payloads(args.repository, args.issue_number)
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
