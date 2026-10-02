import importlib.util
import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from story_slicer.domain.models import StoryBatch
from story_slicer.ports.errors import InputError
from tests.fixtures import story_data


def load_cli() -> dict[str, object]:
    path = Path(__file__).resolve().parents[1] / "cli.py"
    spec = importlib.util.spec_from_file_location("cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return vars(module)


@pytest.mark.parametrize("failure", [False, True])
def test_cli_output_and_cleanup(failure: bool, tmp_path: Path) -> None:
    namespace = load_cli()
    output_path = tmp_path / "stories.json"
    stdout, stderr = StringIO(), StringIO()
    batch = StoryBatch.model_validate({"stories": [story_data()]})
    llm = Mock(aclose=AsyncMock())
    telemetry = Mock()
    execute = AsyncMock(return_value=batch)
    if failure:
        execute.side_effect = InputError("Requirement file cannot be read")
    with (
        patch.dict(
            namespace,
            {
                "EnvironmentConfiguration": Mock(),
                "create_llm": Mock(return_value=llm),
                "OpenTelemetryObservability": Mock(
                    from_settings=Mock(return_value=telemetry)
                ),
                "SliceRequirement": Mock(return_value=Mock(execute=execute)),
            },
        ),
        patch("sys.argv", ["cli.py", "my_feature.yaml", "--output", str(output_path)]),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        status = namespace["main"]()  # type: ignore[operator]
    assert status == int(failure)
    execute.assert_awaited_once_with("my_feature.yaml")
    llm.aclose.assert_awaited_once()
    telemetry.close.assert_called_once()
    if failure:
        assert not stdout.getvalue()
        assert not output_path.exists()
        assert stderr.getvalue() == "Error: Requirement file cannot be read\n"
    else:
        assert json.loads(output_path.read_text()) == batch.model_dump()
        assert str(output_path) in stdout.getvalue()
        assert not stderr.getvalue()


def test_cli_saves_default_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    namespace = load_cli()
    batch = StoryBatch.model_validate({"stories": [story_data()]})
    with (
        patch.dict(namespace, {"slice_yaml": AsyncMock(return_value=batch)}),
        patch("sys.argv", ["cli.py", "input.yaml"]),
    ):
        assert namespace["main"]() == 0  # type: ignore[operator]
    assert json.loads((tmp_path / "stories.json").read_text()) == batch.model_dump()


def test_cli_reports_output_write_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    namespace = load_cli()
    batch = StoryBatch.model_validate({"stories": [story_data()]})
    with (
        patch.dict(namespace, {"slice_yaml": AsyncMock(return_value=batch)}),
        patch("sys.argv", ["cli.py", "input.yaml", "--output", str(tmp_path)]),
    ):
        assert namespace["main"]() == 1  # type: ignore[operator]
    output = capsys.readouterr()
    assert "Cannot save stories" in output.err
    assert not output.out
