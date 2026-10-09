from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from intention_refiner.domain.integration import SourceProvenance

RequirementField = Literal[
    "id", "title", "problem_statement", "target", "business_value", "business_scope",
    "ex_scope", "kpi", "desired_outcomes",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Requirement(StrictModel):
    id: str | None = None
    title: str | None = None
    problem_statement: str | None = None
    target: str | None = None
    business_value: str | None = None
    business_scope: str | None = None
    ex_scope: str | None = None
    kpi: str | None = None
    desired_outcomes: str | None = None


class Suggestion(StrictModel):
    field_name: RequirementField
    tag: Literal["AI_ENHANCED", "FEATURE_IDEA", "CLARIFICATION"]
    text: str = Field(min_length=1)


class Audit(StrictModel):
    ambiguities: list[str]
    missing_information: list[str]
    other_risks: list[str]


class RefinementPayload(StrictModel):
    initiative: Requirement
    suggestions: list[Suggestion]
    audit: Audit


class RefinementResult(RefinementPayload):
    response_time_ms: float = Field(ge=0)


class RefinementReport(RefinementResult):
    source: SourceProvenance | None = None
    provider: str
    model: str
