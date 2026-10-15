"""Strict product requirements and generated story contracts."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]
ProjectIdentifier = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
]
StoryIdentifier = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]*-[1-9][0-9]*$")
]
Priority = Literal["priority:high", "priority:medium", "priority:low"]
Complexity = Literal["low", "medium", "high"]
AlertSeverity = Literal["INFO", "WARNING", "CRITICAL"]


class DomainModel(BaseModel):
    """Reject coercion, unknown fields, and input values in displayed errors."""

    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class Scenario(DomainModel):
    Scenario: NonBlank
    Given: NonBlank
    When: NonBlank
    Then: NonBlank


class StoryAlert(DomainModel):
    severity: AlertSeverity
    rationale: NonBlank


class Story(DomainModel):
    ID: StoryIdentifier
    title: NonBlank
    Who: NonBlank
    Action_What: NonBlank
    Benefit_Why: NonBlank
    Priority: Priority
    acceptance_criteria: Annotated[list[Scenario], Field(min_length=1)]
    tags: list[NonBlank]
    labels: list[NonBlank]
    clarification_comment: Annotated[str, StringConstraints(pattern=r"^$|\S")]

    @model_validator(mode="after")
    def validate_missing_information(self) -> Self:
        if "MISSING_INFO" in self.tags and not self.clarification_comment.startswith(
            "MISSING_INFO"
        ):
            raise ValueError(
                "MISSING_INFO tag requires clarification_comment to start "
                "with the literal"
            )
        if "MISSING_INFO" in self.labels:
            raise ValueError("MISSING_INFO must not be a GitHub label")
        return self


class StoryBatch(DomainModel):
    """Final stories with authoritative, unique application-assigned IDs."""

    stories: Annotated[list[Story], Field(min_length=1)]
    story_count: Annotated[int, Field(ge=1)]
    ambiguity_score: Annotated[float, Field(ge=0.0, le=1.0)]
    estimated_complexity: Complexity
    alerts: list[StoryAlert]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        identifiers = [story.ID for story in self.stories]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Story IDs must be unique within the final batch")
        if self.story_count != len(self.stories):
            raise ValueError("story_count must match the number of stories")
        return self


class Requirement(DomainModel):
    description: NonBlank
    context: NonBlank | None = None
    constraints: list[NonBlank] = Field(default_factory=list)


class RequirementDocument(DomainModel):
    project: ProjectIdentifier
    requirements: Annotated[list[Requirement], Field(min_length=1)]
