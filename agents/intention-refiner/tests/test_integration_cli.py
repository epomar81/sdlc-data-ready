from unittest.mock import MagicMock, patch

import pytest
import yaml
from test_cli import FakeModel

from intention_refiner.cli import main
from intention_refiner.domain.integration import (
    IntegrationError,
    RequirementInput,
    SourceProvenance,
)


@pytest.fixture
def cli_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("INTENTION_REFINER_PROVIDER", "gemini")
    monkeypatch.setenv("INTENTION_REFINER_MODEL", "example")
    monkeypatch.setenv("INTENTION_REFINER_GEMINI_API_KEY", "secret")
    monkeypatch.setenv("INTENTION_REFINER_GITHUB_TOKEN", "token")
    target = tmp_path / "report.yaml"
    monkeypatch.setenv("INTENTION_REFINER_OUTPUT_PATH", str(target))
    return target


def fake_adapter():
    adapter = MagicMock()
    adapter.capabilities = frozenset({"comments", "labels"})
    adapter.normalize.side_effect = lambda source: source
    adapter.read.return_value = RequirementInput(
        "Build app",
        SourceProvenance(
            provider="github", identifier="a/b#1", url="https://github.com/a/b/issues/1"
        ),
    )
    return adapter


def test_cli_remote_read_only_writes_provenance(cli_environment):
    adapter = fake_adapter()
    with (
        patch("intention_refiner.cli.build_integration", return_value=adapter),
        patch("intention_refiner.cli.build_model", return_value=FakeModel()),
    ):
        assert main(["--source", "github", "a/b#1"]) == 0
    adapter.publish.assert_not_called()
    assert (
        yaml.safe_load(cli_environment.read_text())["metadata"]["source"]["identifier"]
        == "a/b#1"
    )


def test_cli_publishes_only_after_save(cli_environment):
    adapter = fake_adapter()

    def publish(request):
        assert cli_environment.exists()

    adapter.publish.side_effect = publish
    with (
        patch("intention_refiner.cli.build_integration", return_value=adapter),
        patch("intention_refiner.cli.build_model", return_value=FakeModel()),
    ):
        assert main(["--source", "github", "a/b#1", "--publish"]) == 0
    adapter.publish.assert_called_once()


def test_cli_source_failure_prevents_model(cli_environment, caplog):
    adapter = fake_adapter()
    adapter.read.side_effect = IntegrationError("timeout")
    with (
        patch("intention_refiner.cli.build_integration", return_value=adapter),
        patch("intention_refiner.cli.build_model") as model,
    ):
        assert main(["--source", "github", "a/b#1"]) == 1
    model.assert_not_called()
    assert not cli_environment.exists()
    assert sum(record.levelname == "ERROR" for record in caplog.records) == 1


def test_cli_save_failure_prevents_publish(cli_environment):
    adapter = fake_adapter()
    with (
        patch("intention_refiner.cli.build_integration", return_value=adapter),
        patch("intention_refiner.cli.build_model", return_value=FakeModel()),
        patch(
            "intention_refiner.cli.YamlReportWriter.write",
            side_effect=OSError("disk full"),
        ),
    ):
        assert main(["--source", "github", "a/b#1", "--publish"]) == 1
    adapter.publish.assert_not_called()


def test_cli_publication_failure_preserves_yaml(cli_environment, caplog):
    adapter = fake_adapter()
    adapter.publish.side_effect = IntegrationError("rate_limit")
    with (
        patch("intention_refiner.cli.build_integration", return_value=adapter),
        patch("intention_refiner.cli.build_model", return_value=FakeModel()),
    ):
        assert main(["--source", "github", "a/b#1", "--publish"]) == 1
    assert (
        yaml.safe_load(cli_environment.read_text())["initiative"]["title"]
        == "Reserve cars"
    )
    assert sum(record.levelname == "ERROR" for record in caplog.records) == 1


def test_cli_rejects_file_publication(cli_environment):
    with patch("intention_refiner.cli.build_model") as model:
        assert main(["idea.txt", "--publish"]) == 1
    model.assert_not_called()


def test_cli_suppresses_http_transport_url_logs(cli_environment, caplog):
    import logging

    adapter = fake_adapter()

    def read(source):
        logging.getLogger("httpx").info(
            "HTTP Request: GET https://private.example/issue"
        )
        return RequirementInput("Idea")

    adapter.read.side_effect = read
    with (
        patch("intention_refiner.cli.build_integration", return_value=adapter),
        patch("intention_refiner.cli.build_model", return_value=FakeModel()),
    ):
        assert main(["--source", "github", "a/b#1"]) == 0
    assert "private.example" not in caplog.text
