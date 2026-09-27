import json
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from intention_refiner.cli import main


class FakeModel:
    def generate(self, prompt):
        return json.dumps({
            "initiative": {"title": "Reserve cars"},
            "suggestions": [],
            "audit": {"ambiguities": [], "missing_information": [], "metric_gaps": [], "other_risks": []},
            "refinement_proposals": [],
        })


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


def test_cli_missing_input_leaves_output_untouched(tmp_path, monkeypatch):
    target = tmp_path / "report.yaml"
    target.write_text("original")
    monkeypatch.setenv("INTENTION_REFINER_PROVIDER", "gemini")
    monkeypatch.setenv("INTENTION_REFINER_MODEL", "example")
    monkeypatch.setenv("INTENTION_REFINER_GEMINI_API_KEY", "secret")
    monkeypatch.setenv("INTENTION_REFINER_OUTPUT_PATH", str(target))

    errors = StringIO()
    with redirect_stderr(errors):
        code = main([str(tmp_path / "missing.txt")])

    assert code == 1
    assert target.read_text() == "original"
    assert "missing.txt" in errors.getvalue()


def test_cli_invalid_model_output_leaves_output_untouched(tmp_path, monkeypatch):
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
            return "invalid JSON"

    errors = StringIO()
    with patch("intention_refiner.cli.build_model", return_value=BadModel()), redirect_stderr(errors):
        code = main([str(source)])

    assert code == 1
    assert target.read_text() == "original"
    assert "invalid requirements JSON" in errors.getvalue()
