import json
import logging
from contextlib import contextmanager

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
        from intention_refiner.application.ports import ModelResponse
        return ModelResponse(text=self.response, prompt_tokens=12, completion_tokens=8, total_tokens=20)


def model_response(payload):
    return json.dumps(payload)


def test_refine_preserves_unknown_fields_and_labels_suggestions():
    response = {
        "initiative": {"title": "Reserve cars", "target": None},
        "suggestions": [
            {"field_name": "target", "tag": "AI_ENHANCED", "text": "[IA ENHANCED] Consider customers booking online."},
            {"field_name": "target", "tag": "AI_ENHANCED", "text": "Online customers"},
        ],
        "audit": {"ambiguities": ["fast"], "missing_information": ["target"], "other_risks": []},
    }
    model = FakeModel(model_response(response))

    result = RefineInitiative(model).execute("Build a fast booking site")

    assert result.initiative.title == "Reserve cars"
    assert result.initiative.target is None
    assert result.suggestions[0].field_name == "target"
    assert result.audit.ambiguities == []
    assert result.suggestions[-1].tag == "CLARIFICATION"
    assert result.suggestions[-1].text == "Could you clarify: fast?"
    assert result.suggestions[1].text == "Online customers"
    assert result.suggestions[1].tag == "AI_ENHANCED"
    assert "Build a fast booking site" in model.prompt
    assert result.response_time_ms >= 0


def test_refine_removes_repeated_paragraphs_and_converts_ambiguities_to_questions():
    response = {
        "initiative": {
            "problem_statement": "Users cannot share playlists.\n\nSharing should be public or private.",
            "business_scope": "Users cannot share playlists.\n\nCreate playlist controls.",
        },
        "suggestions": [],
        "audit": {
            "ambiguities": ["It is unclear how private links are accessed."],
            "missing_information": [], "other_risks": [],
        },
    }

    result = RefineInitiative(FakeModel(model_response(response))).execute("Build playlists")

    assert result.initiative.business_scope == "Create playlist controls."
    assert result.audit.ambiguities == []
    assert result.suggestions == [
        Suggestion(
            field_name="business_scope", tag="CLARIFICATION",
            text="Could you clarify: It is unclear how private links are accessed?",
        )
    ]


def test_refine_drops_metric_suggestion_already_stated_in_initiative():
    response = {
        "initiative": {"kpi": "Increase retention by 15% next quarter."},
        "suggestions": [{
            "field_name": "kpi", "tag": "AI_ENHANCED",
            "text": "Increase retention by 15% next quarter.",
        }],
        "audit": {"ambiguities": [], "missing_information": [], "other_risks": []},
    }

    result = RefineInitiative(FakeModel(model_response(response))).execute("Improve retention")

    assert result.suggestions == []


def test_refine_rejects_removed_missing_info_tag():
    response = {
        "initiative": {"business_value": None, "kpi": None},
        "suggestions": [{
            "field_name": "business_value", "tag": "MISSING_INFO",
            "text": "Reduce support effort by 20%.",
        }],
        "audit": {
            "ambiguities": [], "missing_information": ["No success metric supplied."],
            "other_risks": [],
        },
    }

    with pytest.raises(InvalidModelResponse):
        RefineInitiative(FakeModel(model_response(response))).execute("Build a booking app")


def test_refine_prompt_requires_proactive_enhancements_and_preserved_source():
    model = FakeModel(model_response({
        "initiative": {}, "suggestions": [],
        "audit": {"ambiguities": [], "missing_information": [], "other_risks": []},
    }))

    RefineInitiative(model).execute("Original ticket sentence.")

    assert "Use suggestion tags AI_ENHANCED, FEATURE_IDEA, or CLARIFICATION" in model.prompt
    assert "[IA ENHANCED]" in model.prompt
    assert "Preserve every original ticket sentence verbatim" in model.prompt


def test_refine_records_model_telemetry_without_content():
    class RecordingTelemetry:
        def __init__(self):
            self.spans = []
            self.requests = []

        @contextmanager
        def span(self, name, attributes):
            self.spans.append((name, attributes))
            yield object()

        def record_model_request(self, metrics):
            self.requests.append(metrics)

    telemetry = RecordingTelemetry()
    result = RefineInitiative(FakeModel(model_response({
        "initiative": {}, "suggestions": [],
        "audit": {"ambiguities": [], "missing_information": [], "other_risks": []},
    })), telemetry).execute("private initiative text")

    assert result.initiative.title is None
    assert telemetry.spans == [("model.request", {"provider": "fakemodel", "model": "unknown"})]
    assert telemetry.requests[0].succeeded is True
    assert telemetry.requests[0].total_tokens == 20
    assert "private initiative text" not in repr(telemetry.spans)


def test_failed_model_request_records_sanitized_error_telemetry():
    class RecordingSpan:
        status = None

        def set_status(self, status):
            self.status = status

    class RecordingTelemetry:
        def __init__(self):
            self.span_object = RecordingSpan()
            self.requests = []

        @contextmanager
        def span(self, name, attributes):
            yield self.span_object

        def record_model_request(self, metrics):
            self.requests.append(metrics)

    class FailingModel:
        def generate(self, prompt):
            raise RuntimeError("private prompt content")

    telemetry = RecordingTelemetry()
    with pytest.raises(RuntimeError):
        RefineInitiative(FailingModel(), telemetry).execute("private initiative content")

    assert telemetry.span_object.status.description == "RuntimeError"
    assert telemetry.requests[0].succeeded is False
    assert "private" not in repr((telemetry.span_object.status, telemetry.requests))


def test_refine_logs_structured_request_summary_and_suggestion_events(caplog):
    response = {"initiative": {}, "suggestions": [
        {"field_name": "target", "tag": "AI_ENHANCED", "text": "[IA ENHANCED] Identify intended users."}
    ], "audit": {"ambiguities": [], "missing_information": [], "other_risks": []}}
    with caplog.at_level(logging.INFO):
        RefineInitiative(FakeModel(model_response(response))).execute("Build an app")

    request_log = next(record for record in caplog.records if getattr(record, "event", None) == "model_request_completed")
    assert request_log.prompt_tokens == 12
    assert request_log.completion_tokens == 8
    assert request_log.total_tokens == 20
    suggestion_log = next(record for record in caplog.records if getattr(record, "event", None) == "suggestion_created")
    assert suggestion_log.field_name == "target"
    assert suggestion_log.tag == "AI_ENHANCED"
    assert "Generated tag" not in caplog.text


def test_refine_raises_for_empty_input():
    with pytest.raises(ValueError, match="Input file is empty"):
        RefineInitiative(FakeModel("{}")).execute("  ")


@pytest.mark.parametrize("response", ["not json", "{}", '{"initiative": []}', '{"initiative": {"title": 7}}'])
def test_refine_rejects_invalid_model_output(response):
    with pytest.raises(InvalidModelResponse):
        RefineInitiative(FakeModel(response)).execute("An idea")


def test_refine_prompt_requires_report_schema_shape():
    model = FakeModel(model_response({
        "initiative": {}, "suggestions": [],
        "audit": {"ambiguities": [], "missing_information": [], "other_risks": []},
    }))

    RefineInitiative(model).execute("An idea")

    assert '"initiative"' in model.prompt
    assert '"suggestions"' in model.prompt
    assert '"refinement_proposals"' not in model.prompt
    assert "application adds these values" in model.prompt
    assert '"apiVersion"' not in model.prompt


def test_refine_accepts_json_fence():
    response = f'```json\n{model_response({"initiative": {}, "suggestions": [], "audit": {"ambiguities": [], "missing_information": [], "other_risks": []}})}\n```'

    result = RefineInitiative(FakeModel(response)).execute("An idea")

    assert result.initiative.id is None


def test_domain_rejects_nonexistent_suggestion_field():
    with pytest.raises(ValidationError):
        Suggestion(field_name="imaginary", tag="AI_ENHANCED", text="Guess")


def test_refine_rejects_removed_kpis_and_outcomes_field():
    response = {
        "initiative": {"kpis_and_outcomes": "Legacy field"},
        "suggestions": [],
        "audit": {"ambiguities": [], "missing_information": [], "other_risks": []},
    }

    with pytest.raises(InvalidModelResponse):
        RefineInitiative(FakeModel(model_response(response))).execute("An idea")


def test_requirement_has_reference_fields():
    assert set(Requirement.model_fields) == {
        "id", "title", "problem_statement", "target", "business_value", "business_scope",
        "ex_scope", "kpi", "desired_outcomes",
    }


def test_report_rejects_removed_audit_and_proposal_fields():
    response = {
        "initiative": {}, "suggestions": [],
        "audit": {
            "ambiguities": [], "missing_information": [], "metric_gaps": [], "other_risks": [],
        },
        "refinement_proposals": [{"field_name": "kpi", "proposed_text": "Measure retention"}],
    }

    with pytest.raises(InvalidModelResponse):
        RefineInitiative(FakeModel(model_response(response))).execute("An idea")
