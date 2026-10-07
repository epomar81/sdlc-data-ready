import argparse
import logging
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import ValidationError

from intention_refiner.adapters.files import TextFileReader, YamlReportWriter
from intention_refiner.adapters.github import GitHubAdapter
from intention_refiner.adapters.integration_http import CircuitBreaker
from intention_refiner.adapters.integrations import (
    AdapterDependencies,
    JiraAdapter,
)
from intention_refiner.adapters.models import ModelRequestError, build_model
from intention_refiner.application.integrations import (
    LoadRequirement,
    PublicationRequest,
    PublishRequirement,
)
from intention_refiner.application.refine import RefineInitiative
from intention_refiner.config import LabelPolicy, Settings
from intention_refiner.console_logging import configure_logging
from intention_refiner.domain.integration import IntegrationError, SourceReference
from intention_refiner.domain.models import RefinementReport
from intention_refiner.telemetry import Telemetry

logger = logging.getLogger(__name__)


def build_integration(dependencies: AdapterDependencies):
    if dependencies.config.provider == "github":
        return GitHubAdapter(dependencies)
    return JiraAdapter(dependencies)


def main(argv: list[str] | None = None) -> int:
    correlation_id = str(uuid4())
    configure_logging(correlation_id)
    parser = argparse.ArgumentParser(
        description="Refine one software initiative into a YAML report"
    )
    parser.add_argument(
        "input_file", help="UTF-8 file path or remote issue identifier/URL"
    )
    parser.add_argument("--source", choices=("file", "github", "jira"), default="file")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish comments and labels to the source issue",
    )
    parser.add_argument(
        "--integration-config", type=Path, help="YAML label mapping configuration"
    )
    args = parser.parse_args(argv)
    telemetry = None
    try:
        if args.publish and args.source == "file":
            raise ValueError("--publish requires a remote issue source")
        settings = Settings()
        telemetry = Telemetry(settings.telemetry_enabled, settings.metrics_exporter)
        with (
            ExitStack() as stack,
            telemetry.span("intention_refiner.run", {"correlation_id": correlation_id}),
        ):
            source = SourceReference(args.source, args.input_file)
            adapter = TextFileReader()
            labels = None
            if args.source != "file":
                config = settings.integration_config(args.source)
                client = stack.enter_context(httpx.Client())
                adapter = build_integration(
                    AdapterDependencies(config, client, CircuitBreaker(), telemetry)
                )
                source = adapter.normalize(source)
                if args.publish:
                    labels = LabelPolicy.load(args.integration_config).for_source(
                        source
                    )
            requirement = LoadRequirement(adapter, telemetry).execute(source)
            result = RefineInitiative(build_model(settings), telemetry).execute(
                requirement.text
            )
            report = RefinementReport(
                **result.model_dump(),
                provider=settings.provider,
                model=settings.model,
                source=requirement.provenance,
            )
            YamlReportWriter().write(report, settings.output_path)
            print(f"Report saved to {settings.output_path}")
            if args.publish:
                PublishRequirement(adapter, telemetry).execute(
                    PublicationRequest(source, report, labels)
                )
                print("Publication completed")
        return 0
    except IntegrationError as exc:
        logger.error(
            "Error: %s; completed operations: %s; uncertain operation: %s",
            exc,
            ",".join(exc.completed_operations) or "none",
            exc.uncertain_operation or "none",
        )
        return 1
    except ValidationError:
        logger.error("Error: Invalid configuration or report contract")
        return 1
    except (OSError, ValueError, ModelRequestError) as exc:
        logger.error("Error: %s", exc)
        return 1
    finally:
        if telemetry is not None:
            telemetry.shutdown()
