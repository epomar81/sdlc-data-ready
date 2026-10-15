"""Strict LLM output parsing and authoritative story numbering."""

import json
from typing import Annotated, NoReturn

from pydantic import Field, JsonValue

from story_slicer.domain.models import (
    Complexity,
    DomainModel,
    Story,
    StoryAlert,
    StoryBatch,
)


class _StoryEnvelope(DomainModel):
    stories: Annotated[list[dict[str, JsonValue]], Field(min_length=1)]
    story_count: int
    ambiguity_score: float
    estimated_complexity: Complexity
    alerts: list[StoryAlert]


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"Invalid JSON constant: {value}")


def validate_stories(text: str, project: str) -> StoryBatch:
    data = json.loads(
        text, object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )
    envelope = _StoryEnvelope.model_validate(data)
    stories: list[Story] = []
    for number, candidate in enumerate(envelope.stories, start=1):
        story = Story.model_validate(candidate)
        stories.append(
            Story.model_validate(story.model_dump() | {"ID": f"{project}-{number}"})
        )
    return StoryBatch(
        stories=stories,
        story_count=envelope.story_count,
        ambiguity_score=envelope.ambiguity_score,
        estimated_complexity=envelope.estimated_complexity,
        alerts=envelope.alerts,
    )
