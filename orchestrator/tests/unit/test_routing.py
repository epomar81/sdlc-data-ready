from orchestrator.domain.events import IssueWebhook
from orchestrator.domain.routing import Route, route_issue_event


def event(
    action: str, labels: list[str], added_label: str | None = None
) -> IssueWebhook:
    return IssueWebhook.model_validate(
        {
            "action": action,
            "issue": {
                "number": 7,
                "title": "Add an export option",
                "body": "Allow users to export reports.",
                "html_url": "https://github.com/acme/app/issues/7",
                "labels": [{"name": name} for name in labels],
            },
            "repository": {"full_name": "acme/app"},
            "label": {"name": added_label} if added_label else None,
        }
    )


def test_opened_without_ready_label_routes_to_refiner() -> None:
    assert route_issue_event(event("opened", ["bug"])) is Route.REFINER


def test_opened_with_ready_label_is_ignored() -> None:
    assert route_issue_event(event("opened", ["ready-for-slicing"])) is Route.IGNORE


def test_matching_added_label_routes_to_slicer() -> None:
    assert (
        route_issue_event(event("labeled", ["bug"], "ready-for-slicing"))
        is Route.SLICER
    )


def test_other_added_label_is_ignored_case_sensitively() -> None:
    assert route_issue_event(event("labeled", [], "Ready-for-slicing")) is Route.IGNORE
