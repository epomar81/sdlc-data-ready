import argparse
import logging
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from intention_refiner.adapters.files import TextFileReader, YamlReportWriter
from intention_refiner.adapters.models import ModelRequestError, build_model
from intention_refiner.application.refine import RefineInitiative
from intention_refiner.config import Settings
from intention_refiner.console_logging import configure_logging
from intention_refiner.domain.models import RefinementReport
from intention_refiner.telemetry import Telemetry, record_exception

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    correlation_id = str(uuid4())
    configure_logging(correlation_id)
    parser = argparse.ArgumentParser(description="Refine one software initiative into a YAML report")
    parser.add_argument("input_file", type=Path, help="UTF-8 text file containing one initiative")
    args = parser.parse_args(argv)
    telemetry = None
    try:
        settings = Settings()
        telemetry = Telemetry(settings.telemetry_enabled)
        with telemetry.span("intention_refiner.run", {"correlation_id": correlation_id}) as span:
            try:
                text = TextFileReader().read(args.input_file)
                result = RefineInitiative(build_model(settings), telemetry).execute(text)
                report = RefinementReport(
                    **result.model_dump(), provider=settings.provider, model=settings.model,
                )
                YamlReportWriter().write(report, settings.output_path)
            except (OSError, ValueError, ValidationError, ModelRequestError) as exc:
                record_exception(span, exc)
                logger.error("Error: %s", exc)
                return 1
        print(f"Report saved to {settings.output_path}")
        return 0
    except (OSError, ValueError, ValidationError, ModelRequestError) as exc:
        logger.error("Error: %s", exc)
        return 1
    finally:
        if telemetry is not None:
            telemetry.shutdown()
