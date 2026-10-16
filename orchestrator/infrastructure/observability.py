"""OpenTelemetry recording for validated story batch outputs."""

import logging
import os

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from orchestrator.application.ports import BatchObservabilityPort

logger = logging.getLogger(__name__)


class OpenTelemetryBatchObservability(BatchObservabilityPort):
    def __init__(self) -> None:
        self._traces: TracerProvider | None = None
        self._metrics: MeterProvider | None = None
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        export_enabled = os.getenv("OTEL_EXPORT_MODE", "disabled") == "otlp"
        resource = Resource.create(
            {
                "service.name": os.getenv(
                    "OTEL_SERVICE_NAME", "sdlc-data-ready-orchestrator"
                )
            }
        )
        if endpoint and export_enabled:
            endpoint = endpoint.rstrip("/")
            timeout = float(os.getenv("OTEL_EXPORT_TIMEOUT_SECONDS", "10"))
            interval = int(
                float(os.getenv("OTEL_EXPORT_INTERVAL_SECONDS", "30")) * 1000
            )
            self._traces = TracerProvider(resource=resource, shutdown_on_exit=False)
            self._traces.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=timeout),
                    schedule_delay_millis=interval,
                    export_timeout_millis=int(timeout * 1000),
                )
            )
            reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", timeout=timeout),
                export_interval_millis=interval,
                export_timeout_millis=int(timeout * 1000),
            )
            self._metrics = MeterProvider(
                resource=resource,
                metric_readers=[reader],
                shutdown_on_exit=False,
            )
        else:
            self._traces = TracerProvider(resource=resource, shutdown_on_exit=False)
            self._metrics = MeterProvider(resource=resource, shutdown_on_exit=False)
        meter = self._metrics.get_meter("sdlc_data_ready_orchestrator")
        self._story_count = meter.create_histogram(
            "story_batch.story_count", unit="{story}"
        )
        self._ambiguity_score = meter.create_histogram(
            "story_batch.ambiguity_score", unit="1"
        )
        self._alerts = meter.create_counter("story_batch.alerts")
        self._tracer = self._traces.get_tracer("sdlc_data_ready_orchestrator")

    def record_batch(self, batch: object) -> None:
        story_count = getattr(batch, "story_count", None)
        ambiguity_score = getattr(batch, "ambiguity_score", None)
        alerts = getattr(batch, "alerts", None)
        if type(story_count) is not int or not isinstance(ambiguity_score, float):
            logger.warning("Skipping telemetry for invalid story batch")
            return
        try:
            self._story_count.record(story_count)
            self._ambiguity_score.record(ambiguity_score)
            for alert in alerts or []:
                severity = getattr(alert, "severity", None)
                rationale = getattr(alert, "rationale", None)
                if not isinstance(severity, str) or not isinstance(rationale, str):
                    continue
                self._alerts.add(1, {"severity": severity})
                with self._tracer.start_as_current_span("story_batch.alert") as span:
                    span.add_event(
                        "story_batch.alert",
                        {"severity": severity, "rationale": rationale},
                    )
        except Exception:
            logger.warning("Story batch telemetry recording failed")

    def close(self) -> None:
        for provider in (self._traces, self._metrics):
            if provider is None:
                continue
            try:
                provider.force_flush()
                provider.shutdown()
            except Exception:
                logger.warning("OpenTelemetry shutdown failed")
