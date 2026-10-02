import pytest

from story_slicer.adapters.requirements.yaml import YamlRequirementParser
from story_slicer.ports.errors import InputError


def test_schema_error_reports_all_field_paths_without_input_values() -> None:
    content = (
        b"project: SHOP\nrequirements:\n  - description: 123456789\n"
        b"  - context: confidential-content\n"
    )
    with pytest.raises(InputError) as caught:
        YamlRequirementParser().parse(content)
    message = str(caught.value)
    assert "requirements.0.description: Input should be a valid string" in message
    assert "requirements.1.description: Field required" in message
    assert "123456789" not in message
    assert "confidential-content" not in message


@pytest.mark.parametrize(
    "content, diagnostic",
    [
        (b"project: SHOP\nrequirements: [\n", "line 3, column 1"),
        (b"project: SHOP\nproject: PRIVATE\n", "line 2, column 1"),
        (b"project: \xff", "must be UTF-8"),
    ],
)
def test_parse_error_reports_location_or_encoding(
    content: bytes, diagnostic: str
) -> None:
    with pytest.raises(InputError) as caught:
        YamlRequirementParser().parse(content)
    message = str(caught.value)
    assert diagnostic in message
    assert "PRIVATE" not in message
    assert caught.value.__cause__ is None


def test_refined_initiative_preserves_business_details_and_review_context() -> None:
    content = b"""initiative:
  id: null
  title: Mobile Favorite Music Lists
  target: mobile app users
  business_scope: Create lists and sync offline.
  desired_outcomes: Manage favorite music quickly.
suggestions:
  - field_name: business_value
    tag: MISSING_INFO
    text: Which business metrics should improve?
audit:
  missing_information:
    - Conflict resolution is unspecified.
refinement_proposals:
  - field_name: kpi
    proposed_text: p95 latency under 500ms
    rationale: Measurable target
metadata:
  provider: gemini
"""
    document = YamlRequirementParser().parse(content)
    assert document.project == "Mobile-Favorite-Music-Lists"
    requirement = document.requirements[0]
    assert "Manage favorite music quickly." in requirement.description
    assert requirement.context is not None
    for detail in [
        "mobile app users",
        "Create lists and sync offline.",
        "MISSING_INFO",
        "Which business metrics should improve?",
        "Conflict resolution is unspecified.",
        "p95 latency under 500ms",
    ]:
        assert detail in requirement.context


def test_refined_initiative_requires_meaningful_business_content() -> None:
    with pytest.raises(InputError):
        YamlRequirementParser().parse(b"initiative: {title: Empty}\n")
