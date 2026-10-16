import asyncio
from types import SimpleNamespace

from orchestrator.application.router import IssueEventDispatcher
from orchestrator.domain.events import IssueWebhook


class Refiner:
    def __init__(self) -> None:
        self.events = []

    def refine(self, event) -> None:
        self.events.append(event)


class Slicer:
    def __init__(self, batch: object) -> None:
        self.batch = batch
        self.events = []

    async def slice(self, event) -> object:
        self.events.append(event)
        return self.batch


class Publisher:
    def __init__(self) -> None:
        self.calls = []
        self.result = object()

    async def publish(self, event, batch) -> object:
        self.calls.append((event, batch))
        return self.result


class Observability:
    def __init__(self) -> None:
        self.batches = []

    def record_batch(self, batch) -> None:
        self.batches.append(batch)


def event(action: str, label: str | None = None) -> IssueWebhook:
    return IssueWebhook.model_validate(
        {
            "action": action,
            "issue": {
                "number": 1,
                "title": "A title",
                "body": "A body",
                "html_url": "https://github.com/acme/app/issues/1",
                "labels": [],
            },
            "repository": {"full_name": "acme/app"},
            "label": {"name": label} if label else None,
        }
    )


def test_dispatcher_routes_refiner_without_blocking_event_loop() -> None:
    refiner = Refiner()
    slicer = Slicer(object())
    publisher = Publisher()
    telemetry = Observability()
    dispatcher = IssueEventDispatcher(refiner, slicer, publisher, telemetry)

    asyncio.run(dispatcher.execute(event("opened")))

    assert len(refiner.events) == 1
    assert slicer.events == []
    assert publisher.calls == []


def test_dispatcher_records_batch_then_publishes_slicer_output() -> None:
    batch = object()
    refiner = Refiner()
    slicer = Slicer(batch)
    publisher = Publisher()
    telemetry = Observability()
    dispatcher = IssueEventDispatcher(refiner, slicer, publisher, telemetry)
    issue_event = event("labeled", "ready-for-slicing")

    asyncio.run(dispatcher.execute(issue_event))

    assert slicer.events == [issue_event]
    assert telemetry.batches == [batch]
    assert publisher.calls == [(issue_event, batch)]


def test_dispatcher_retains_partial_publication_failure_and_comment_field(
    caplog,
) -> None:
    story = SimpleNamespace(
        clarification_comment="MISSING_INFO Please clarify the role."
    )
    batch = SimpleNamespace(
        stories=[story], story_count=1, ambiguity_score=0.5, alerts=[]
    )
    publisher = Publisher()
    publisher.result = SimpleNamespace(failures=["APP-1: comment request failed"])
    dispatcher = IssueEventDispatcher(
        Refiner(), Slicer(batch), publisher, Observability()
    )

    asyncio.run(dispatcher.execute(event("labeled", "ready-for-slicing")))

    assert publisher.calls[0][1].stories[0].clarification_comment.startswith(
        "MISSING_INFO"
    )
    assert "APP-1: comment request failed" in caplog.text
