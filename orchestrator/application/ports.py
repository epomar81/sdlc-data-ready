"""Ports implemented by agent and telemetry infrastructure adapters."""

from typing import Protocol

from orchestrator.domain.events import IssueWebhook


class RefinerPort(Protocol):
    def refine(self, event: IssueWebhook) -> object:
        """Run Agent 01 against the issue text."""


class SlicerPort(Protocol):
    async def slice(self, event: IssueWebhook) -> object:
        """Run Agent 02 and return its validated story batch."""


class StoryPublisherPort(Protocol):
    async def publish(self, event: IssueWebhook, batch: object) -> object:
        """Publish the validated batch to GitHub."""


class BatchObservabilityPort(Protocol):
    def record_batch(self, batch: object) -> None:
        """Record validated batch metrics and alert events."""


class EventDispatcherPort(Protocol):
    async def execute(self, event: IssueWebhook) -> None:
        """Route and execute an issue event."""
