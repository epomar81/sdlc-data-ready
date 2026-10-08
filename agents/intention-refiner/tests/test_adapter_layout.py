from pathlib import Path

from intention_refiner.adapters.filesystem.files import TextFileReader
from intention_refiner.adapters.llm.models import GeminiAdapter
from intention_refiner.adapters.requirements.github import GitHubAdapter


def test_adapters_are_grouped_by_responsibility():
    assert TextFileReader.__module__ == "intention_refiner.adapters.filesystem.files"
    assert GeminiAdapter.__module__ == "intention_refiner.adapters.llm.models"
    assert GitHubAdapter.__module__ == "intention_refiner.adapters.requirements.github"


def test_adapter_implementation_modules_live_in_responsibility_packages():
    adapter_root = Path(__file__).parents[1] / "intention_refiner" / "adapters"
    assert not list(adapter_root.glob("*.py"))
