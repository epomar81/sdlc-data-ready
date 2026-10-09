from contextlib import nullcontext
from dataclasses import dataclass

from pydantic import ValidationError

from intention_refiner.application.ports import (
    IssuePublisherPort,
    RequirementSourcePort,
)
from intention_refiner.config import SourceLabels
from intention_refiner.domain.integration import (
    IntegrationError,
    PublicationResult,
    RequirementInput,
    SourceReference,
)
from intention_refiner.domain.models import RefinementReport
from intention_refiner.telemetry import PublicationMetrics


@dataclass(frozen=True)
class PublicationRequest:
    source: SourceReference
    report: RefinementReport
    labels: SourceLabels

    def required_labels(self) -> tuple[str, ...]:
        names = []
        if any(item.tag == "CLARIFICATION" for item in self.report.suggestions):
            names.append(self.labels.clarification)
        if any(
            item.tag in {"AI_ENHANCED", "FEATURE_IDEA"}
            for item in self.report.suggestions
        ):
            names.append(self.labels.ai_review)
        return tuple(dict.fromkeys(names))


class LoadRequirement:
    def __init__(self, source: RequirementSourcePort, telemetry=None):
        self.source = source
        self.telemetry = telemetry

    def execute(self, reference: SourceReference) -> RequirementInput:
        context = (
            self.telemetry.span("source.read", {"provider": reference.provider})
            if self.telemetry
            else nullcontext()
        )
        with context:
            result = self.source.read(reference)
            if not result.text.strip():
                raise ValueError("Requirement input is empty")
            return result


class PublishRequirement:
    def __init__(self, publisher: IssuePublisherPort, telemetry=None):
        self.publisher = publisher
        self.telemetry = telemetry

    def execute(self, request: PublicationRequest) -> PublicationResult:
        context = (
            self.telemetry.span("publication", {"provider": request.source.provider})
            if self.telemetry
            else nullcontext()
        )
        try:
            with context:
                if not {"comments", "labels"} <= self.publisher.capabilities:
                    raise IntegrationError("unsupported", "capabilities")
                result = self.publisher.publish(request)
        except (IntegrationError, ValidationError) as exc:
            error = (
                exc
                if isinstance(exc, IntegrationError)
                else IntegrationError("validation", "publication result")
            )
            if self.telemetry:
                self.telemetry.record_publication(
                    PublicationMetrics(request.source.provider, False, error.reason)
                )
            raise error from None
        if self.telemetry:
            self.telemetry.record_publication(
                PublicationMetrics(request.source.provider, True)
            )
        return result
