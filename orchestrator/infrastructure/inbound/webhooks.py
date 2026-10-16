"""GitHub webhook HTTP adapter."""

import json
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import ValidationError

from orchestrator.application.ports import EventDispatcherPort
from orchestrator.domain.events import IssueWebhook
from orchestrator.domain.routing import Route, route_issue_event
from orchestrator.infrastructure.github import verify_signature


def _issue_event(payload: object, action: str) -> IssueWebhook:
    if not isinstance(payload, dict):
        raise ValueError("Webhook payload must be a JSON object")
    issue = payload.get("issue")
    repository = payload.get("repository")
    if not isinstance(issue, dict) or not isinstance(repository, dict):
        raise ValueError("Issue and repository fields are required")
    labels = issue.get("labels", [])
    if not isinstance(labels, list) or any(
        not isinstance(item, dict) for item in labels
    ):
        raise ValueError("Issue labels must be a list of objects")
    added_label = payload.get("label")
    if added_label is not None and not isinstance(added_label, dict):
        raise ValueError("Added label must be an object")
    normalized = {
        "action": action,
        "issue": {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "body": issue.get("body"),
            "html_url": issue.get("html_url"),
            "labels": [{"name": label.get("name")} for label in labels],
        },
        "repository": {"full_name": repository.get("full_name")},
        "label": {"name": added_label.get("name")} if added_label is not None else None,
    }
    return IssueWebhook.model_validate(normalized)


def create_webhook_router(
    dispatcher: EventDispatcherPort, webhook_secret: str | None = None
) -> APIRouter:
    router = APIRouter()

    @router.post("/webhooks/github")
    async def github_webhook(
        request: Request, background_tasks: BackgroundTasks
    ) -> dict[str, str]:
        secret = webhook_secret or os.getenv("GITHUB_WEBHOOK_SECRET", "")
        if not secret:
            raise HTTPException(
                status_code=503, detail="Webhook secret is not configured"
            )
        body = await request.body()
        signature = request.headers.get("x-hub-signature-256")
        if not verify_signature(body, signature, secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        event_name = request.headers.get("x-github-event")
        if not event_name:
            raise HTTPException(status_code=400, detail="Missing GitHub event header")
        if event_name != "issues":
            return {"status": "ignored"}
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(
                status_code=400, detail="Invalid JSON payload"
            ) from None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="Webhook payload must be an object"
            )
        action = payload.get("action")
        if action != "opened" and action != "labeled":
            return {"status": "ignored"}
        try:
            event = _issue_event(payload, action)
        except (ValidationError, ValueError):
            raise HTTPException(
                status_code=422, detail="Invalid issue webhook payload"
            ) from None
        if action == "labeled" and event.label is None:
            raise HTTPException(
                status_code=422, detail="Labeled event is missing its label"
            )
        if route_issue_event(event) is Route.IGNORE:
            return {"status": "ignored"}
        background_tasks.add_task(dispatcher.execute, event)
        return {"status": "accepted"}

    return router
