import pytest
from pydantic import ValidationError

from story_slicer.domain.models import (
    Requirement,
    RequirementDocument,
    Story,
    StoryBatch,
)
from tests.fixtures import story_data


def test_valid_story_round_trip_and_schema() -> None:
    story = Story.model_validate(story_data())
    assert Story.model_validate_json(story.model_dump_json()) == story
    assert set(Story.model_json_schema()["required"]) == set(story_data())


def test_missing_story_field_rejected() -> None:
    data = story_data()
    del data["Who"]
    with pytest.raises(ValidationError):
        Story.model_validate(data)


def test_strict_story_and_scenario_validation() -> None:
    changes: list[dict[str, object]] = [
        {"title": 123},
        {"title": " "},
        {"extra": True},
        {"acceptance_criteria": []},
        {"Priority": "URGENT"},
    ]
    for change in changes:
        with pytest.raises(ValidationError):
            Story.model_validate(story_data() | change)
    data = story_data()
    data["acceptance_criteria"][0]["Then"] = " "
    with pytest.raises(ValidationError):
        Story.model_validate(data)


def test_missing_info_accepts_meaningful_string_and_list_metadata() -> None:
    story = Story.model_validate(
        story_data()
        | {
            "tags": ["MISSING_INFO"],
            "clarification": "Which carrier?",
            "suggestions": ["Keep the carrier unspecified until clarified."],
        }
    )
    assert story.tags == ["MISSING_INFO"]


def test_missing_info_requires_both_metadata_fields() -> None:
    for metadata in [
        {"clarification": "Question", "suggestions": []},
        {"clarification": "", "suggestions": ["Assumption"]},
        {"clarification": " ", "suggestions": ["Assumption"]},
    ]:
        with pytest.raises(ValidationError):
            Story.model_validate(story_data() | {"tags": ["MISSING_INFO"]} | metadata)


def test_final_batch_requires_unique_ids() -> None:
    story = Story.model_validate(story_data())
    assert StoryBatch(stories=[story]).stories == [story]
    with pytest.raises(ValidationError):
        StoryBatch(stories=[story, story])


def test_requirement_document_defaults_and_boundaries() -> None:
    requirement = Requirement(description="Track orders")
    assert requirement.context is None and requirement.constraints == []
    assert (
        RequirementDocument(project="SHOP", requirements=[requirement]).project
        == "SHOP"
    )
    with pytest.raises(ValidationError):
        RequirementDocument(project="SHOP", requirements=[])
    with pytest.raises(ValidationError):
        Requirement.model_validate({"description": "Track", "max_retries": 3})
