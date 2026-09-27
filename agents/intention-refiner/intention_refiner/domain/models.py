from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RequirementField = Literal[
    "id", "title", "problem_statement", "target", "business_value", "business_scope",
    "ex_scope", "kpi", "desired_outcomes", "kpis_and_outcomes",
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
    kpis_and_outcomes: str | None = None


class Suggestion(StrictModel):
    field_name: RequirementField
    tag: Literal["MISSING_INFO", "AI_ENHANCED", "FEATURE_IDEA", "CLARIFICATION"]
    text: str = Field(min_length=1)


class Audit(StrictModel):
    ambiguities: list[str]
    missing_information: list[str]
    metric_gaps: list[str]
    other_risks: list[str]


class RefinementProposal(StrictModel):
    field_name: RequirementField
    proposed_text: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class RefinementPayload(StrictModel):
    initiative: Requirement
    suggestions: list[Suggestion]
    audit: Audit
    refinement_proposals: list[RefinementProposal]


class RefinementResult(RefinementPayload):
    response_time_ms: float = Field(ge=0)


class RefinementReport(RefinementResult):
    provider: str
    model: str
