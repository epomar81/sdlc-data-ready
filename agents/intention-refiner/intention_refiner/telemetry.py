import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from typing import Literal

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from intention_refiner.domain.integration import FailureReason, Provider


@dataclass(frozen=True)
class ModelRequestMetrics:
    provider: str
    model: str
    duration_seconds: float
    succeeded: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class PublicationMetrics:
    provider: Provider
    succeeded: bool
    reason: FailureReason | None = None


@dataclass(frozen=True)
class PublicationPayloadMetrics:
    provider: Provider
    operation: str
    size_bytes: int


class Telemetry:
    def __init__(self, enabled: bool, exporter: Literal["console", "otlp"] = "console"):
        resource = Resource.create({"service.name": "intention-refiner"})
        self._tracer_provider = None
        metric_exporter = (
            OTLPMetricExporter()
            if exporter == "otlp"
            else ConsoleMetricExporter(out=StringIO())
        )
        reader = PeriodicExportingMetricReader(
            metric_exporter, export_interval_millis=10000
        )
        self._meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        meter = self._meter_provider.get_meter("intention_refiner")
        integration_meter = self._meter_provider.get_meter("agent.integration.metrics")
        self._publications_success = integration_meter.create_counter(
            "publications_success_total"
        )
        self._publications_failed = integration_meter.create_counter(
            "publications_failed_total"
        )
        self._publication_payload = integration_meter.create_histogram(
            "publication_payload_bytes", unit="By"
        )
        if enabled:
            self._tracer_provider = TracerProvider(resource=resource)
            self._tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter())
            )
            tracer = self._tracer_provider.get_tracer("intention_refiner")
        else:
            tracer = trace.get_tracer("intention_refiner")
        self._tracer = tracer
        self._requests = meter.create_counter("intention_refiner.model.requests")
        self._duration = meter.create_histogram(
            "intention_refiner.model.duration", unit="s"
        )
        self._tokens = meter.create_counter(
            "intention_refiner.model.tokens", unit="{token}"
        )

    @contextmanager
    def span(self, name: str, attributes: dict[str, str]) -> Iterator[object]:
        with self._tracer.start_as_current_span(
            name,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield span
            except Exception as exc:
                record_exception(span, exc)
                raise

    def record_model_request(self, data: ModelRequestMetrics) -> None:
        attributes = {
            "provider": data.provider,
            "model": data.model,
            "outcome": "success" if data.succeeded else "error",
        }
        self._requests.add(1, attributes)
        self._duration.record(data.duration_seconds, attributes)
        if data.succeeded:
            self._tokens.add(data.prompt_tokens, {**attributes, "token.type": "prompt"})
            self._tokens.add(
                data.completion_tokens, {**attributes, "token.type": "completion"}
            )
            self._tokens.add(data.total_tokens, {**attributes, "token.type": "total"})

    def record_publication(self, event: PublicationMetrics) -> None:
        attributes = {"provider": event.provider}
        if event.succeeded:
            self._publications_success.add(1, attributes)
        else:
            attributes["reason"] = event.reason or "remote_error"
            self._publications_failed.add(1, attributes)

    def record_publication_payload(self, event: PublicationPayloadMetrics) -> None:
        self._publication_payload.record(
            event.size_bytes, {"provider": event.provider, "operation": event.operation}
        )

    def shutdown(self) -> None:
        for provider in (self._tracer_provider, self._meter_provider):
            if provider is not None:
                try:
                    provider.force_flush(timeout_millis=5000)
                except Exception:  # noqa: BLE001 - exporter failures must not change the command result
                    logging.getLogger(__name__).warning(
                        "Telemetry flush failed",
                        extra={"event": "telemetry_flush_failed", "error_type": "ExporterError"},
                    )
                try:
                    provider.shutdown()
                except Exception:  # noqa: BLE001 - exporter failures must not change the command result
                    logging.getLogger(__name__).warning(
                        "Telemetry shutdown failed",
                        extra={"event": "telemetry_shutdown_failed", "error_type": "ExporterError"},
                    )


def record_exception(span: Span, error: Exception) -> None:
    span.set_status(Status(StatusCode.ERROR, type(error).__name__))
