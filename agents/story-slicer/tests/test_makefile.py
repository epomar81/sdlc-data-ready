import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("build", "uv build"),
        ("test", "uv run --locked pytest"),
        ("run", 'uv run --locked python cli.py "my feature.yaml"'),
    ],
)
def test_make_targets_use_uv(target: str, expected: str) -> None:
    result = subprocess.run(
        ["make", "--dry-run", target, "FILE=my feature.yaml"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout


def test_make_run_requires_yaml_path(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "make",
            "-f",
            str(ROOT / "Makefile"),
            "run",
            "FILE=",
            "STORY_SLICER_INPUT_PATH=",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "make run FILE=my_feature.yaml" in result.stderr


def test_make_run_uses_configured_input_path() -> None:
    result = subprocess.run(
        ["make", "--dry-run", "run", "STORY_SLICER_INPUT_PATH=requirements/input.yaml"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert 'uv run --locked python cli.py "requirements/input.yaml"' in result.stdout


def test_make_run_explicit_file_overrides_configured_path() -> None:
    result = subprocess.run(
        [
            "make",
            "--dry-run",
            "run",
            "FILE=override.yaml",
            "STORY_SLICER_INPUT_PATH=configured.yaml",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert 'uv run --locked python cli.py "override.yaml"' in result.stdout


def test_make_quality_runs_lint_and_tests() -> None:
    result = subprocess.run(
        ["make", "--dry-run", "quality"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "uv run --locked ruff check ." in result.stdout
    assert "uv run --locked ruff format --check ." in result.stdout
    assert "uv run --locked mypy" in result.stdout
    assert "uv run --locked pytest" in result.stdout


def test_make_run_passes_output_path() -> None:
    for output in ["stories.json", "results/my stories.json"]:
        result = subprocess.run(
            ["make", "--dry-run", "run", "FILE=input.yaml", f"OUTPUT={output}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert f'--output "{output}"' in result.stdout


def test_make_run_reloads_envrc_before_starting_cli(tmp_path: Path) -> None:
    import os

    (tmp_path / ".envrc").write_text(
        "export STORY_SLICER_GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta\n"
        "export STORY_SLICER_INPUT_PATH=current.yaml\n"
    )
    uv = tmp_path / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'test "$STORY_SLICER_GEMINI_BASE_URL" = '
        '"https://generativelanguage.googleapis.com/v1beta" || exit 9\n'
        'test "$5" = "current.yaml" || exit 10\n'
    )
    uv.chmod(0o755)
    result = subprocess.run(
        ["make", "-f", str(ROOT / "Makefile"), "run"],
        cwd=tmp_path,
        env=os.environ
        | {
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "STORY_SLICER_GEMINI_BASE_URL": "https://aistudio.google.com/api-keys",
            "STORY_SLICER_INPUT_PATH": "",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
