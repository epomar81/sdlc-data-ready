from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode


@dataclass(frozen=True)
class ModelRequestMetrics:
    provider: str
    model: str
    duration_seconds: float
    succeeded: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class Telemetry:
    def __init__(self, enabled: bool):
        resource = Resource.create({"service.name": "intention-refiner"})
        self._tracer_provider = None
        self._meter_provider = None
        if enabled:
            self._tracer_provider = TracerProvider(resource=resource)
            self._tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter())
            )
            reader = PeriodicExportingMetricReader(OTLPMetricExporter())
            self._meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
            tracer = self._tracer_provider.get_tracer("intention_refiner")
            meter = self._meter_provider.get_meter("intention_refiner")
        else:
            tracer = trace.get_tracer("intention_refiner")
            meter = metrics.get_meter("intention_refiner")
        self._tracer = tracer
        self._requests = meter.create_counter("intention_refiner.model.requests")
        self._duration = meter.create_histogram("intention_refiner.model.duration", unit="s")
        self._tokens = meter.create_counter("intention_refiner.model.tokens", unit="{token}")

    @contextmanager
    def span(self, name: str, attributes: dict[str, str]) -> Iterator[object]:
        with self._tracer.start_as_current_span(name, attributes=attributes) as span:
            yield span

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
            self._tokens.add(data.completion_tokens, {**attributes, "token.type": "completion"})
            self._tokens.add(data.total_tokens, {**attributes, "token.type": "total"})

    def shutdown(self) -> None:
        if self._tracer_provider is not None:
            self._tracer_provider.shutdown()
        if self._meter_provider is not None:
            self._meter_provider.shutdown()


def record_exception(span: Span, error: Exception) -> None:
    span.set_status(Status(StatusCode.ERROR, type(error).__name__))
