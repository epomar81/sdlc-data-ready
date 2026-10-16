import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from story_slicer.domain.models import (
    Requirement,
    RequirementDocument,
    Story,
    StoryBatch,
)
from tests.fixtures import story_batch_data, story_data


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
        {"Priority": "HIGH"},
    ]
    for change in changes:
        with pytest.raises(ValidationError):
            Story.model_validate(story_data() | change)
    data = story_data()
    data["acceptance_criteria"][0]["Then"] = " "
    with pytest.raises(ValidationError):
        Story.model_validate(data)


def test_missing_info_requires_plain_text_in_comment_and_not_as_label() -> None:
    story = Story.model_validate(
        story_data()
        | {
            "tags": ["MISSING_INFO"],
            "clarification_comment": "MISSING_INFO: Which carrier? Keep unspecified.",
            "labels": ["needs-clarification"],
        }
    )
    assert story.tags == ["MISSING_INFO"]
    assert "MISSING_INFO" in story.clarification_comment


def test_missing_info_comment_and_label_are_validated() -> None:
    changes: list[dict[str, object]] = [
        {"clarification_comment": "Which carrier?"},
        {"clarification_comment": "", "labels": ["MISSING_INFO"]},
    ]
    for change in changes:
        invalid_story = story_data()
        invalid_story.update(
            {
                "tags": ["MISSING_INFO"],
                "clarification_comment": "MISSING_INFO: Which carrier?",
            }
        )
        invalid_story.update(change)
        with pytest.raises(ValidationError):
            Story.model_validate(invalid_story)


def test_final_batch_requires_unique_ids() -> None:
    story = Story.model_validate(story_data())
    batch_data = story_batch_data()
    assert StoryBatch.model_validate(batch_data).stories == [story]
    with pytest.raises(ValidationError):
        StoryBatch.model_validate(
            batch_data | {"stories": [story_data(), story_data()]}
        )


def test_batch_metrics_and_alerts_are_strict_and_consistent() -> None:
    batch = StoryBatch.model_validate(story_batch_data())
    assert batch.story_count == len(batch.stories) == 1
    changes: list[dict[str, object]] = [
        {"ambiguity_score": -0.1},
        {"ambiguity_score": 1.1},
        {"estimated_complexity": "urgent"},
        {"story_count": 2},
        {"alerts": [{"severity": "NOTICE", "rationale": "Risk"}]},
    ]
    for change in changes:
        with pytest.raises(ValidationError):
            invalid_batch = story_batch_data()
            invalid_batch.update(change)
            StoryBatch.model_validate(invalid_batch)


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


def test_checked_in_story_batch_matches_pydantic_contract() -> None:
    root = Path(__file__).parents[1]
    batch = StoryBatch.model_validate_json((root / "stories.json").read_text())
    schema = json.loads((root / "schemas/stories.schema.json").read_text())

    assert schema == StoryBatch.model_json_schema()
    assert all(story.labels for story in batch.stories)
