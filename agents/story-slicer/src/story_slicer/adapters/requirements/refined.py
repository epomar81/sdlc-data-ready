"""Normalize initiative-refiner documents without losing review context."""

import re
from typing import Self

from pydantic import Field, JsonValue, model_validator

from story_slicer.domain.models import (
    DomainModel,
    NonBlank,
    Requirement,
    RequirementDocument,
)


class RefinedInitiative(DomainModel):
    id: NonBlank | None = None
    title: NonBlank
    problem_statement: NonBlank | None = None
    target: NonBlank | None = None
    business_value: NonBlank | None = None
    business_scope: NonBlank | None = None
    ex_scope: NonBlank | None = None
    kpi: NonBlank | None = None
    desired_outcomes: NonBlank | None = None
    kpis_and_outcomes: NonBlank | None = None

    @model_validator(mode="after")
    def validate_business_content(self) -> Self:
        if not any(
            (self.problem_statement, self.business_scope, self.desired_outcomes)
        ):
            raise ValueError(
                "Initiative requires a problem statement, scope, or desired outcomes"
            )
        return self


class RefinedDocument(DomainModel):
    initiative: RefinedInitiative
    suggestions: list[dict[str, JsonValue]] = Field(default_factory=list)
    audit: dict[str, JsonValue] = Field(default_factory=dict)
    refinement_proposals: list[dict[str, JsonValue]] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    def to_requirement(self) -> RequirementDocument:
        initiative = self.initiative
        identifier = initiative.id or initiative.title
        project = re.sub(r"[^A-Za-z0-9_-]+", "-", identifier).strip("-_")
        if not project or not project[0].isalpha():
            project = "INIT-" + project
        description = (
            initiative.desired_outcomes
            or initiative.business_scope
            or initiative.problem_statement
        )
        return RequirementDocument(
            project=project,
            requirements=[
                Requirement(
                    description=f"{initiative.title}: {description}",
                    context=self.model_dump_json(indent=2),
                )
            ],
        )
