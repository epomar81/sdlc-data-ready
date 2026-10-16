"""Application-level routing and agent dispatch."""

import asyncio
import logging

from orchestrator.application.ports import (
    BatchObservabilityPort,
    RefinerPort,
    SlicerPort,
    StoryPublisherPort,
)
from orchestrator.domain.events import IssueWebhook
from orchestrator.domain.routing import Route, route_issue_event

logger = logging.getLogger(__name__)


class IssueEventDispatcher:
    def __init__(
        self,
        refiner: RefinerPort,
        slicer: SlicerPort,
        publisher: StoryPublisherPort,
        observability: BatchObservabilityPort,
    ) -> None:
        self._refiner = refiner
        self._slicer = slicer
        self._publisher = publisher
        self._observability = observability

    async def execute(self, event: IssueWebhook) -> None:
        route = route_issue_event(event)
        if route is Route.IGNORE:
            return
        if route is Route.REFINER:
            await asyncio.to_thread(self._run_refiner, event)
            return
        await self._run_slicer(event)

    def _run_refiner(self, event: IssueWebhook) -> None:
        try:
            self._refiner.refine(event)
        except Exception:
            logger.exception(
                "Refiner workflow failed",
                extra={"event": "agent_workflow_failed", "agent": "refiner"},
            )

    async def _run_slicer(self, event: IssueWebhook) -> None:
        try:
            batch = await self._slicer.slice(event)
            self._observability.record_batch(batch)
            result = await self._publisher.publish(event, batch)
            for failure in getattr(result, "failures", []):
                logger.warning(
                    "Story publication action failed: %s",
                    failure,
                    extra={
                        "event": "story_publication_failed",
                        "failure": failure,
                    },
                )
        except Exception:
            logger.exception(
                "Slicer workflow failed",
                extra={"event": "agent_workflow_failed", "agent": "slicer"},
            )
