import json
import logging
from unittest.mock import patch

from intention_refiner.cli import main
from intention_refiner.console_logging import JsonLogFormatter


class FakeModel:
    def generate(self, prompt):
        from intention_refiner.application.ports import ModelResponse
        return ModelResponse(text=json.dumps({
            "initiative": {"title": "Reserve cars"},
            "suggestions": [],
            "audit": {"ambiguities": [], "missing_information": [], "metric_gaps": [], "other_risks": []},
            "refinement_proposals": [],
        }), prompt_tokens=12, completion_tokens=8, total_tokens=20)


def test_json_log_formatter_emits_valid_json():
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "Failure: %s", ("unavailable",), None)

    assert json.loads(JsonLogFormatter().format(record)) == {
        "level": "error",
        "message": "Failure: unavailable",
    }


def test_cli_writes_report(tmp_path, monkeypatch):
    source = tmp_path / "idea.txt"
    source.write_text("Build a car reservation site")
    target = tmp_path / "report.yaml"
    monkeypatch.setenv("INTENTION_REFINER_PROVIDER", "gemini")
    monkeypatch.setenv("INTENTION_REFINER_MODEL", "example")
    monkeypatch.setenv("INTENTION_REFINER_GEMINI_API_KEY", "secret")
    monkeypatch.setenv("INTENTION_REFINER_OUTPUT_PATH", str(target))

    with patch("intention_refiner.cli.build_model", return_value=FakeModel()):
        code = main([str(source)])

    assert code == 0
    assert target.exists()


def test_cli_missing_input_logs_error_once_and_leaves_output_untouched(tmp_path, monkeypatch, caplog):
    target = tmp_path / "report.yaml"
    target.write_text("original")
    monkeypatch.setenv("INTENTION_REFINER_PROVIDER", "gemini")
    monkeypatch.setenv("INTENTION_REFINER_MODEL", "example")
    monkeypatch.setenv("INTENTION_REFINER_GEMINI_API_KEY", "secret")
    monkeypatch.setenv("INTENTION_REFINER_OUTPUT_PATH", str(target))

    code = main([str(tmp_path / "missing.txt")])

    assert code == 1
    assert target.read_text() == "original"
    assert sum(record.levelname == "ERROR" for record in caplog.records) == 1
    assert "missing.txt" in caplog.text


def test_cli_invalid_model_output_logs_error_once(tmp_path, monkeypatch, caplog):
    source = tmp_path / "idea.txt"
    source.write_text("Build a car reservation site")
    target = tmp_path / "report.yaml"
    target.write_text("original")
    monkeypatch.setenv("INTENTION_REFINER_PROVIDER", "gemini")
    monkeypatch.setenv("INTENTION_REFINER_MODEL", "example")
    monkeypatch.setenv("INTENTION_REFINER_GEMINI_API_KEY", "secret")
    monkeypatch.setenv("INTENTION_REFINER_OUTPUT_PATH", str(target))

    class BadModel:
        def generate(self, prompt):
            from intention_refiner.application.ports import ModelResponse
            return ModelResponse("invalid JSON", prompt_tokens=2, completion_tokens=1, total_tokens=3)

    with patch("intention_refiner.cli.build_model", return_value=BadModel()):
        code = main([str(source)])

    assert code == 1
    assert target.read_text() == "original"
    assert "invalid requirements JSON" in caplog.text
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(error_logs) == 1
    assert "invalid requirements JSON" in error_logs[0].message
