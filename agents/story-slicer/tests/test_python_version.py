import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_project_supports_python_311() -> None:
    project = (ROOT / "pyproject.toml").read_text()
    readme = (ROOT / "README.md").read_text()
    lockfile = (ROOT / "uv.lock").read_text()

    assert 'requires-python = ">=3.11,<3.12"' in project
    assert 'target-version = "py311"' in project
    assert 'python_version = "3.11"' in project
    assert "Requires Python 3.11" in readme
    assert 'requires-python = "==3.11.*"' in lockfile


def test_source_parses_as_python_311() -> None:
    for path in (ROOT / "src").rglob("*.py"):
        ast.parse(path.read_text(), filename=str(path), feature_version=(3, 11))
