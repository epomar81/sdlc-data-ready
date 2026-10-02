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
MetadataText = Annotated[str, StringConstraints(pattern=r"^$|\S")] | list[NonBlank]
Priority = Literal["HIGH", "MEDIUM", "LOW"]


class DomainModel(BaseModel):
    """Reject coercion, unknown fields, and input values in displayed errors."""

    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class Scenario(DomainModel):
    Scenario: NonBlank
    Given: NonBlank
    When: NonBlank
    Then: NonBlank


class IntelligenceMetadata(DomainModel):
    tags: list[NonBlank]
    clarification: MetadataText
    suggestions: MetadataText

    @model_validator(mode="after")
    def validate_missing_information(self) -> Self:
        if "MISSING_INFO" in self.tags and (
            not self.clarification or not self.suggestions
        ):
            raise ValueError(
                "MISSING_INFO requires nonempty clarification and suggestions"
            )
        return self


class Story(IntelligenceMetadata):
    ID: StoryIdentifier
    title: NonBlank
    Who: NonBlank
    Action_What: NonBlank
    Benefit_Why: NonBlank
    Priority: Priority
    acceptance_criteria: Annotated[list[Scenario], Field(min_length=1)]


class StoryBatch(DomainModel):
    """Final stories with authoritative, unique application-assigned IDs."""

    stories: Annotated[list[Story], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        identifiers = [story.ID for story in self.stories]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Story IDs must be unique within the final batch")
        return self


class Requirement(DomainModel):
    description: NonBlank
    context: NonBlank | None = None
    constraints: list[NonBlank] = Field(default_factory=list)


class RequirementDocument(DomainModel):
    project: ProjectIdentifier
    requirements: Annotated[list[Requirement], Field(min_length=1)]
