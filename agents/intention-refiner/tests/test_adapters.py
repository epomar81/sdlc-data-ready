from unittest.mock import MagicMock, patch

import pytest
import yaml
from pydantic import ValidationError

from intention_refiner.adapters.files import YamlReportWriter
from intention_refiner.adapters.models import GeminiAdapter, NvidiaAdapter
from intention_refiner.config import ModelConfig, Settings
from intention_refiner.domain.models import Audit, RefinementReport, Requirement


def test_settings_load_selected_provider_from_environment(monkeypatch):
    monkeypatch.setenv("INTENTION_REFINER_PROVIDER", "nvidia")
    monkeypatch.setenv("INTENTION_REFINER_MODEL", "example-model")
    monkeypatch.setenv("INTENTION_REFINER_NVIDIA_API_KEY", "secret")
    monkeypatch.setenv("INTENTION_REFINER_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("INTENTION_REFINER_OUTPUT_PATH", "custom.yaml")

    settings = Settings()

    assert settings.provider == "nvidia"
    assert settings.model_config_for_provider() == ModelConfig(api_key="secret", model="example-model", timeout_seconds=12)
    assert str(settings.output_path) == "custom.yaml"


def test_settings_require_selected_provider_key(monkeypatch):
    monkeypatch.setenv("INTENTION_REFINER_PROVIDER", "gemini")
    monkeypatch.setenv("INTENTION_REFINER_MODEL", "example-model")
    monkeypatch.delenv("INTENTION_REFINER_GEMINI_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings()


def test_settings_reject_invalid_timeout(monkeypatch):
    monkeypatch.setenv("INTENTION_REFINER_PROVIDER", "nvidia")
    monkeypatch.setenv("INTENTION_REFINER_MODEL", "example-model")
    monkeypatch.setenv("INTENTION_REFINER_NVIDIA_API_KEY", "secret")
    monkeypatch.setenv("INTENTION_REFINER_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValidationError):
        Settings()


def test_gemini_adapter_uses_configured_model():
    config = ModelConfig(api_key="secret", model="gemini-example", timeout_seconds=12)
    response = MagicMock(text="{\"ok\": true}")
    with patch("intention_refiner.adapters.models.genai.Client") as client:
        client.return_value.models.generate_content.return_value = response

        result = GeminiAdapter(config).generate("prompt")

    assert result == '{"ok": true}'
    client.assert_called_once()
    assert client.return_value.models.generate_content.call_args.kwargs["model"] == "gemini-example"


def test_nvidia_adapter_uses_configured_model():
    config = ModelConfig(api_key="secret", model="nvidia-example", timeout_seconds=12)
    with patch("intention_refiner.adapters.models.OpenAI") as client:
        client.return_value.chat.completions.create.return_value.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]

        result = NvidiaAdapter(config).generate("prompt")

    assert result == '{"ok": true}'
    client.assert_called_once()
    assert client.return_value.chat.completions.create.call_args.kwargs["model"] == "nvidia-example"


def test_yaml_writer_saves_structured_report(tmp_path):
    target = tmp_path / "report.yaml"
    report = RefinementReport(
        initiative=Requirement(title="Reserve cars"), suggestions=[],
        audit=Audit(ambiguities=[], missing_information=[], metric_gaps=[], other_risks=[]),
        refinement_proposals=[], provider="gemini", model="example", response_time_ms=1.5,
    )

    YamlReportWriter().write(report, target)

    saved = yaml.safe_load(target.read_text())
    assert saved["initiative"]["title"] == "Reserve cars"
    assert saved["initiative"]["target"] is None
    assert saved["metadata"]["provider"] == "gemini"


def test_yaml_writer_preserves_existing_report_on_failure(tmp_path):
    target = tmp_path / "report.yaml"
    target.write_text("original")
    report = MagicMock()
    report.model_dump.side_effect = ValueError("bad report")

    with pytest.raises(ValueError):
        YamlReportWriter().write(report, target)

    assert target.read_text() == "original"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["report.yaml"]
