"""Slice YAML files or GitHub issues into user stories."""

import argparse
import asyncio
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import httpx
from pydantic import ValidationError

from story_slicer.adapters.configuration.environment import EnvironmentConfiguration
from story_slicer.adapters.filesystem.local import LocalFileSystem
from story_slicer.adapters.llm.selection import create_llm
from story_slicer.adapters.observability.opentelemetry import OpenTelemetryObservability
from story_slicer.adapters.requirements.github import (
    GitHubRequirementLoader,
    GitHubStoryPublisher,
    parse_issue_reference,
)
from story_slicer.adapters.requirements.yaml import YamlRequirementParser
from story_slicer.adapters.requirements.yaml_loader import (
    YamlLoaderDependencies,
    YamlRequirementLoader,
)
from story_slicer.application.slice_requirement import (
    SliceRequirement,
    SlicingDependencies,
)
from story_slicer.domain.models import StoryBatch
from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import StorySlicerError
from story_slicer.ports.requirements import RequirementSource, StoryPublishRequest


@dataclass(frozen=True)
class LoadedConfiguration:
    settings: RuntimeSettings

    def load(self) -> RuntimeSettings:
        return self.settings


def save_stories(batch: StoryBatch, output: Path) -> None:
    """Replace the output only after the complete JSON has been written."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(batch.model_dump_json(indent=2) + "\n")
        temporary_path.replace(output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _issue_url(reference: str) -> str:
    owner, repository, number = parse_issue_reference(reference)
    return f"https://github.com/{owner}/{repository}/issues/{number}"


def _repository(value: str) -> str:
    parts = value.split("/")
    if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
        raise ValueError("Repository must use owner/repo")
    if any(char.isspace() for char in value) or "#" in value:
        raise ValueError("Repository must use owner/repo")
    parse_issue_reference(f"{parts[0]}/{parts[1]}#1")
    return value


async def run(args: argparse.Namespace) -> int:
    try:
        source = RequirementSource(kind=args.source, reference=args.input)
    except ValidationError:
        raise StorySlicerError(
            "An explicit nonblank requirement reference is required"
        ) from None
    repository: str | None = None
    source_url: str | None = None
    if args.source == "github":
        owner, repo, _ = parse_issue_reference(args.input)
        repository = f"{owner}/{repo}"
        source_url = _issue_url(args.input)
    settings = EnvironmentConfiguration().load()
    if args.create_tickets:
        if args.target_repo:
            repository = _repository(args.target_repo)
        elif args.source == "yaml":
            if settings.github_repository is None:
                raise StorySlicerError(
                    "Set STORY_SLICER_GITHUB_REPOSITORY or pass "
                    "--target-repo owner/repo"
                )
            repository = _repository(settings.github_repository)

    async with AsyncExitStack() as resources:
        client = httpx.AsyncClient(trust_env=False)
        resources.push_async_callback(client.aclose)
        llm = create_llm(settings)
        resources.push_async_callback(llm.aclose)
        telemetry = OpenTelemetryObservability.from_settings(settings)
        resources.callback(telemetry.close)
        if args.source == "github":
            loader = GitHubRequirementLoader(settings, client)
        else:
            loader = YamlRequirementLoader(
                YamlLoaderDependencies(
                    filesystem=LocalFileSystem(),
                    parser=YamlRequirementParser(),
                    max_bytes=settings.max_input_bytes,
                    timeout_seconds=settings.session_timeout_seconds,
                )
            )
        dependencies = SlicingDependencies(
            configuration=LoadedConfiguration(settings),
            requirement_loader=loader,
            llm=llm,
            observability=telemetry,
        )
        batch = await SliceRequirement(dependencies).execute(source)
        save_stories(batch, args.output)
        print(f"Saved stories to {args.output}")
        if not args.create_tickets:
            return 0
        assert repository is not None
        result = await GitHubStoryPublisher(settings, client).publish(
            StoryPublishRequest(
                batch=batch, repository=repository, source_url=source_url
            )
        )
        for url in result.created:
            print(f"Created GitHub ticket: {url}")
        for failure in result.failures:
            print(f"Ticket creation failed: {failure}", file=sys.stderr)
        return int(bool(result.failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="YAML file path or GitHub issue reference")
    parser.add_argument(
        "--source", choices=("yaml", "github"), default="yaml", help="Input source"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("stories.json"),
        help="Output JSON file (default: stories.json)",
    )
    parser.add_argument(
        "--create-tickets",
        action="store_true",
        help="Create one GitHub issue for each generated story",
    )
    parser.add_argument(
        "--target-repo", help="GitHub owner/repo for created story issues"
    )
    args = parser.parse_args()
    if args.source == "yaml" and args.output.resolve() == Path(args.input).resolve():
        parser.error("Output file must differ from the input file")
    try:
        return asyncio.run(run(args))
    except StorySlicerError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
