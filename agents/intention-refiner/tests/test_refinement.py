import json

import pytest
from pydantic import ValidationError

from intention_refiner.application.refine import InvalidModelResponse, RefineInitiative
from intention_refiner.domain.models import Requirement, Suggestion


class FakeModel:
    def __init__(self, response):
        self.response = response
        self.prompt = None

    def generate(self, prompt):
        self.prompt = prompt
        return self.response


def test_refine_preserves_unknown_fields_and_labels_suggestions():
    response = {
        "initiative": {"title": "Reserve cars", "target": None},
        "suggestions": [
            {"field_name": "target", "tag": "MISSING_INFO", "text": "Consider customers booking online."}
        ],
        "audit": {"ambiguities": ["fast"], "missing_information": ["target"], "metric_gaps": [], "other_risks": []},
        "refinement_proposals": [
            {"field_name": "target", "proposed_text": "Online customers", "rationale": "Confirm with the owner."}
        ],
    }
    model = FakeModel(json.dumps(response))

    result = RefineInitiative(model).execute("Build a fast booking site")

    assert result.initiative.title == "Reserve cars"
    assert result.initiative.target is None
    assert result.suggestions[0].field_name == "target"
    assert result.audit.ambiguities == ["fast"]
    assert result.refinement_proposals[0].proposed_text == "Online customers"
    assert "Build a fast booking site" in model.prompt
    assert result.response_time_ms >= 0


@pytest.mark.parametrize("response", ["not json", "{}", '{"initiative": []}', '{"initiative": {"title": 7}}'])
def test_refine_rejects_invalid_model_output(response):
    with pytest.raises(InvalidModelResponse):
        RefineInitiative(FakeModel(response)).execute("An idea")


def test_refine_accepts_json_fence():
    response = '```json\n{"initiative": {}, "suggestions": [], "audit": {"ambiguities": [], "missing_information": [], "metric_gaps": [], "other_risks": []}, "refinement_proposals": []}\n```'

    result = RefineInitiative(FakeModel(response)).execute("An idea")

    assert result.initiative.id is None


def test_domain_rejects_nonexistent_suggestion_field():
    with pytest.raises(ValidationError):
        Suggestion(field_name="imaginary", tag="MISSING_INFO", text="Guess")


def test_requirement_has_reference_fields():
    assert set(Requirement.model_fields) == {
        "id", "title", "problem_statement", "target", "business_value", "business_scope",
        "ex_scope", "kpi", "desired_outcomes", "kpis_and_outcomes",
    }
