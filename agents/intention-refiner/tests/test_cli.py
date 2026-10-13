import json
import logging
from contextlib import nullcontext
from unittest.mock import patch

from intention_refiner.cli import main
from intention_refiner.console_logging import JsonLogFormatter, configure_logging


class FakeModel:
    def generate(self, prompt):
        from intention_refiner.application.ports import ModelResponse
        return ModelResponse(text=json.dumps({
            "initiative": {"title": "Reserve cars"},
            "suggestions": [],
            "audit": {"ambiguities": [], "missing_information": [], "other_risks": []},
        }), prompt_tokens=12, completion_tokens=8, total_tokens=20)


def test_json_log_formatter_emits_valid_json():
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "Failure: %s", ("unavailable",), None)
    record.event = "operation_failed"
    record.duration_ms = 12.5

    fields = json.loads(JsonLogFormatter().format(record))
    assert fields == {
        "timestamp": fields["timestamp"],
        "level": "error",
        "event": "operation_failed",
        "duration_ms": 12.5,
        "message": "Failure: unavailable",
    }
    assert fields["timestamp"].endswith("Z")


def test_json_log_formatter_includes_correlation_id():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "Started", (), None)
    record.correlation_id = "run-123"

    assert json.loads(JsonLogFormatter().format(record)) == {
        "timestamp": json.loads(JsonLogFormatter().format(record))["timestamp"],
        "level": "info",
        "event": "Started",
        "duration_ms": None,
        "message": "Started",
        "correlation_id": "run-123",
    }


def test_configured_logging_suppresses_library_and_debug_records(capsys):
    configure_logging("run-123")

    logging.getLogger("httpx").error("private transport details")
    logging.getLogger("intention_refiner.test").debug("internal state")
    logging.getLogger("intention_refiner.test").info(
        "Operation completed",
        extra={"event": "operation_completed", "duration_ms": 4},
    )

    output = capsys.readouterr()
    records = [json.loads(line) for line in output.err.splitlines()]
    assert len(records) == 1
    assert records[0]["event"] == "operation_completed"
    assert records[0]["duration_ms"] == 4
    assert output.out == ""


def test_cli_writes_report(tmp_path, monkeypatch, capsys):
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
    assert capsys.readouterr().out == ""


def test_cli_records_one_end_to_end_run_on_success_and_failure(tmp_path, monkeypatch):
    from intention_refiner.telemetry import RunMetrics

    source = tmp_path / "idea.txt"
    source.write_text("Build a car reservation site")
    target = tmp_path / "report.yaml"
    monkeypatch.setenv("INTENTION_REFINER_PROVIDER", "gemini")
    monkeypatch.setenv("INTENTION_REFINER_MODEL", "example")
    monkeypatch.setenv("INTENTION_REFINER_GEMINI_API_KEY", "secret")
    monkeypatch.setenv("INTENTION_REFINER_OUTPUT_PATH", str(target))

    class RecordingTelemetry:
        def __init__(self):
            self.runs = []

        def span(self, name, attributes):
            return nullcontext()

        def record_run(self, metrics):
            self.runs.append(metrics)

        def record_model_request(self, metrics):
            pass

        def shutdown(self):
            pass

    telemetry = RecordingTelemetry()
    with (
        patch("intention_refiner.cli.Telemetry", return_value=telemetry),
        patch("intention_refiner.cli.build_model", return_value=FakeModel()),
    ):
        assert main([str(source)]) == 0
        assert main([str(tmp_path / "missing.txt")]) == 1

    assert len(telemetry.runs) == 2
    assert telemetry.runs[0].succeeded is True
    assert telemetry.runs[0].error_type is None
    assert telemetry.runs[1].succeeded is False
    assert telemetry.runs[1].error_type == "command_error"
    assert all(isinstance(metrics, RunMetrics) for metrics in telemetry.runs)
    assert all(metrics.duration_seconds >= 0 for metrics in telemetry.runs)


def test_cli_generates_a_new_correlation_id_for_each_run(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("INTENTION_REFINER_PROVIDER", "gemini")
    monkeypatch.setenv("INTENTION_REFINER_MODEL", "example")
    monkeypatch.setenv("INTENTION_REFINER_GEMINI_API_KEY", "secret")
    for index in range(2):
        source = tmp_path / f"missing-{index}.txt"
        assert main([str(source)]) == 1

    ids = [record.correlation_id for record in caplog.records]
    assert len(ids) == 2
    assert ids[0] != ids[1]


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
