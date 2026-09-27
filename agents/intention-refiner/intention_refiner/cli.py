import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from intention_refiner.adapters.files import TextFileReader, YamlReportWriter
from intention_refiner.adapters.models import ModelRequestError, build_model
from intention_refiner.application.refine import RefineInitiative
from intention_refiner.config import Settings
from intention_refiner.domain.models import RefinementReport


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refine one software initiative into a YAML report")
    parser.add_argument("input_file", type=Path, help="UTF-8 text file containing one initiative")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        text = TextFileReader().read(args.input_file)
        result = RefineInitiative(build_model(settings)).execute(text)
        report = RefinementReport(
            **result.model_dump(), provider=settings.provider, model=settings.model,
        )
        YamlReportWriter().write(report, settings.output_path)
    except (OSError, ValueError, ValidationError, ModelRequestError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Report saved to {settings.output_path}")
    return 0
