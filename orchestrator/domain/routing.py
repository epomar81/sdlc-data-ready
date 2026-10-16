"""Pure event-to-agent routing rules."""

from enum import StrEnum

from orchestrator.domain.events import IssueWebhook

READY_FOR_SLICING = "ready-for-slicing"


class Route(StrEnum):
    IGNORE = "ignore"
    REFINER = "refiner"
    SLICER = "slicer"


def route_issue_event(event: IssueWebhook) -> Route:
    labels = {item.name for item in event.issue.labels}
    if event.action == "opened":
        return Route.IGNORE if READY_FOR_SLICING in labels else Route.REFINER
    if event.action == "labeled" and event.label is not None:
        return Route.SLICER if event.label.name == READY_FOR_SLICING else Route.IGNORE
    return Route.IGNORE
