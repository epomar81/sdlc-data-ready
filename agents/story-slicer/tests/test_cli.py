import importlib.util
import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import pytest

from story_slicer.domain.models import StoryBatch
from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import InputError
from story_slicer.ports.requirements import RequirementSource, StoryPublishResult
from tests.fixtures import settings_data, story_data


def load_cli() -> dict[str, object]:
    path = Path(__file__).resolve().parents[1] / "cli.py"
    spec = importlib.util.spec_from_file_location("cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return vars(module)


def configured_namespace(batch: StoryBatch) -> tuple[dict[str, object], AsyncMock]:
    namespace = load_cli()
    llm = Mock(aclose=AsyncMock())
    telemetry = Mock()
    execute = AsyncMock(return_value=batch)
    client = Mock(aclose=AsyncMock())
    patches = {
        "EnvironmentConfiguration": Mock(
            return_value=Mock(
                load=Mock(return_value=RuntimeSettings.model_validate(settings_data()))
            )
        ),
        "create_llm": Mock(return_value=llm),
        "OpenTelemetryObservability": Mock(from_settings=Mock(return_value=telemetry)),
        "SliceRequirement": Mock(return_value=Mock(execute=execute)),
        "httpx": Mock(AsyncClient=Mock(return_value=client)),
        "YamlRequirementLoader": Mock(),
        "LocalFileSystem": Mock(),
        "YamlRequirementParser": Mock(),
    }
    namespace["_test_patches"] = patches
    namespace["_test_client"] = client
    return namespace, execute


@pytest.mark.parametrize("failure", [False, True])
def test_cli_output_and_cleanup(failure: bool, tmp_path: Path) -> None:
    batch = StoryBatch.model_validate({"stories": [story_data()]})
    namespace, execute = configured_namespace(batch)
    patches = namespace["_test_patches"]
    output_path = tmp_path / "stories.json"
    stdout, stderr = StringIO(), StringIO()
    if failure:
        execute.side_effect = InputError("Requirement file cannot be read")
    with (
        patch.dict(namespace, patches),
        patch("sys.argv", ["cli.py", "my_feature.yaml", "--output", str(output_path)]),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        status = namespace["main"]()  # type: ignore[operator]
    assert status == int(failure)
    execute.assert_awaited_once_with(
        RequirementSource(kind="yaml", reference="my_feature.yaml")
    )
    cast(Mock, namespace["_test_client"]).aclose.assert_awaited_once()
    if failure:
        assert not stdout.getvalue()
        assert not output_path.exists()
        assert stderr.getvalue() == "Error: Requirement file cannot be read\n"
    else:
        assert json.loads(output_path.read_text()) == batch.model_dump()
        assert str(output_path) in stdout.getvalue()
        assert not stderr.getvalue()


def test_cli_defaults_output_to_stories_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    batch = StoryBatch.model_validate({"stories": [story_data()]})
    namespace, _ = configured_namespace(batch)
    with (
        patch.dict(namespace, namespace["_test_patches"]),
        patch("sys.argv", ["cli.py", "input.yaml"]),
    ):
        assert namespace["main"]() == 0  # type: ignore[operator]
    assert json.loads((tmp_path / "stories.json").read_text()) == batch.model_dump()


def test_cli_keeps_json_when_ticket_creation_is_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    batch = StoryBatch.model_validate({"stories": [story_data()]})
    namespace, _ = configured_namespace(batch)
    publisher = Mock(
        publish=AsyncMock(
            return_value=StoryPublishResult(
                created=["https://github.com/acme/shop/issues/3"],
                failures=["SHOP-1: GitHub returned HTTP 422"],
            )
        )
    )
    patches = cast(dict[str, object], namespace["_test_patches"]) | {
        "GitHubStoryPublisher": Mock(return_value=publisher)
    }
    stdout, stderr = StringIO(), StringIO()
    with (
        patch.dict(namespace, patches),
        patch(
            "sys.argv",
            [
                "cli.py",
                "requirements.yaml",
                "--create-tickets",
                "--target-repo",
                "acme/shop",
            ],
        ),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        assert namespace["main"]() == 1  # type: ignore[operator]
    assert json.loads((tmp_path / "stories.json").read_text()) == batch.model_dump()
    assert "issues/3" in stdout.getvalue()
    assert "HTTP 422" in stderr.getvalue()


def test_yaml_ticket_creation_uses_configured_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    batch = StoryBatch.model_validate({"stories": [story_data()]})
    namespace, _ = configured_namespace(batch)
    settings = RuntimeSettings.model_validate(
        settings_data() | {"github_repository": "acme/shop"}
    )
    patches = cast(dict[str, object], namespace["_test_patches"]) | {
        "EnvironmentConfiguration": Mock(
            return_value=Mock(load=Mock(return_value=settings))
        )
    }
    publisher = Mock(
        publish=AsyncMock(return_value=StoryPublishResult(created=[], failures=[]))
    )
    patches["GitHubStoryPublisher"] = Mock(return_value=publisher)
    with (
        patch.dict(namespace, patches),
        patch("sys.argv", ["cli.py", "requirements.yaml", "--create-tickets"]),
    ):
        assert namespace["main"]() == 0  # type: ignore[operator]
    request = publisher.publish.await_args.args[0]
    assert request.repository == "acme/shop"


def test_cli_selects_github_loader_and_source_reference(tmp_path: Path) -> None:
    batch = StoryBatch.model_validate({"stories": [story_data()]})
    namespace, execute = configured_namespace(batch)
    patches = cast(dict[str, object], namespace["_test_patches"]) | {
        "GitHubRequirementLoader": Mock()
    }
    with (
        patch.dict(namespace, patches),
        patch(
            "sys.argv",
            [
                "cli.py",
                "octo/shop#12",
                "--source",
                "github",
                "-o",
                str(tmp_path / "stories.json"),
            ],
        ),
    ):
        assert namespace["main"]() == 0  # type: ignore[operator]
    execute.assert_awaited_once_with(
        RequirementSource(kind="github", reference="octo/shop#12")
    )


def test_yaml_ticket_creation_requires_configured_or_explicit_repository() -> None:
    namespace = load_cli()
    with (
        patch("sys.argv", ["cli.py", "requirements.yaml", "--create-tickets"]),
        redirect_stderr(StringIO()),
    ):
        assert namespace["main"]() == 1  # type: ignore[operator]
