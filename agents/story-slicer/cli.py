"""Run Story Slicer with an explicit YAML requirement file."""

import argparse
import asyncio
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from story_slicer.adapters.configuration.environment import EnvironmentConfiguration
from story_slicer.adapters.filesystem.local import LocalFileSystem
from story_slicer.adapters.llm.selection import create_llm
from story_slicer.adapters.observability.opentelemetry import OpenTelemetryObservability
from story_slicer.adapters.requirements.yaml import YamlRequirementParser
from story_slicer.application.slice_requirement import (
    SliceRequirement,
    SlicingDependencies,
)
from story_slicer.domain.models import StoryBatch
from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import StorySlicerError


@dataclass(frozen=True)
class LoadedConfiguration:
    settings: RuntimeSettings

    def load(self) -> RuntimeSettings:
        return self.settings


async def slice_yaml(path: str) -> StoryBatch:
    settings = EnvironmentConfiguration().load()
    async with AsyncExitStack() as resources:
        llm = create_llm(settings)
        resources.push_async_callback(llm.aclose)
        telemetry = OpenTelemetryObservability.from_settings(settings)
        resources.callback(telemetry.close)
        dependencies = SlicingDependencies(
            configuration=LoadedConfiguration(settings),
            filesystem=LocalFileSystem(),
            parser=YamlRequirementParser(),
            llm=llm,
            observability=telemetry,
        )
        return await SliceRequirement(dependencies).execute(path)


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml_file", help="Path to the YAML requirement file")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("stories.json"),
        help="Output JSON file (default: stories.json)",
    )
    args = parser.parse_args()
    if args.output.resolve() == Path(args.yaml_file).resolve():
        parser.error("Output file must differ from the input file")
    try:
        batch = asyncio.run(slice_yaml(args.yaml_file))
    except StorySlicerError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    try:
        save_stories(batch, args.output)
    except OSError as error:
        print(f"Error: Cannot save stories to {args.output}: {error}", file=sys.stderr)
        return 1
    print(f"Saved stories to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
