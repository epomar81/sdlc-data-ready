"""Interfaces required by the orchestrator's application workflow.

These protocols keep application logic independent from concrete agent,
GitHub, and telemetry implementations. Infrastructure adapters satisfy a
protocol by providing the methods and compatible signatures declared here.
"""

from typing import Protocol

from orchestrator.domain.events import IssueWebhook


class RefinerPort(Protocol):
    """Run the intention-refiner agent for an incoming issue.

    Implementations receive a normalized webhook event and invoke the refiner
    using its issue details. The concrete result is intentionally unspecified
    because the dispatcher only needs the side effect of refinement.
    """

    def refine(self, event: IssueWebhook) -> object:
        """Refine an issue's intent.

        Args:
            event: Validated issue webhook containing the issue title, body,
                repository, and routing metadata.

        Returns:
            The implementation-specific refiner result.

        Raises:
            Exception: An implementation may raise an exception if the agent
                cannot process the issue or its downstream service fails.

        Example:
            ``result = refiner.refine(issue_event)``
        """


class SlicerPort(Protocol):
    """Generate a validated batch of stories from an issue."""

    async def slice(self, event: IssueWebhook) -> object:
        """Run the story-slicer agent for an issue.

        Args:
            event: Validated issue webhook whose issue text is the source for
                story generation.

        Returns:
            The implementation-specific validated story batch.

        Raises:
            Exception: An implementation may raise an exception if generation
                fails, the response is invalid, or a downstream service fails.

        Example:
            ``batch = await slicer.slice(issue_event)``
        """


class StoryPublisherPort(Protocol):
    """Publish generated stories to the source issue's GitHub repository."""

    async def publish(self, event: IssueWebhook, batch: object) -> object:
        """Publish a validated story batch.

        Args:
            event: Validated webhook identifying the source issue and
                repository.
            batch: Validated batch produced by the slicer, in the format
                expected by the concrete publisher adapter.

        Returns:
            The implementation-specific publication result, such as created
            issue identifiers or URLs.

        Raises:
            Exception: An implementation may raise an exception if GitHub
                rejects the request or publication otherwise fails.

        Example:
            ``published = await publisher.publish(issue_event, batch)``
        """


class BatchObservabilityPort(Protocol):
    """Record metrics and alerts associated with a generated story batch."""

    def record_batch(self, batch: object) -> None:
        """Record observability data extracted from a batch.

        Args:
            batch: Validated story batch containing metrics and any alerts
                supported by the implementation.

        Returns:
            ``None``.

        Raises:
            Exception: An implementation may raise an exception if extracting
                or recording the batch's observability data fails.

        Example:
            ``observability.record_batch(batch)``
        """


class EventDispatcherPort(Protocol):
    """Coordinate routing and execution for an issue webhook event."""

    async def execute(self, event: IssueWebhook) -> None:
        """Route an event to the appropriate workflow and execute it.

        Args:
            event: Validated issue webhook to route and process.

        Returns:
            ``None``. Any resulting work is performed by the configured
            collaborators.

        Raises:
            Exception: An implementation may raise an exception if routing or
                workflow execution fails. The webhook adapter schedules this
                operation as a background task.

        Example:
            ``await dispatcher.execute(issue_event)``
        """
