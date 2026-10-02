"""Session traces, bounded metric labels, and structured alert events."""

import logging
from time import time_ns
from uuid import uuid4

from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import (
    INVALID_SPAN_CONTEXT,
    NonRecordingSpan,
    Span,
    StatusCode,
    set_span_in_context,
)

from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.observability import (
    AttemptCompleted,
    CriticalAlert,
    ObservabilityEvent,
    OperationalAlert,
    RepairScheduled,
    SchemaFailure,
    SessionCompleted,
    SessionContext,
    SessionHandle,
)

_LOGGER = logging.getLogger(__name__)


class OpenTelemetryObservability:
    def __init__(self, traces: TracerProvider, metrics: MeterProvider) -> None:
        self._traces = traces
        self._metrics = metrics
        self._tracer = traces.get_tracer("story_slicer")
        meter = metrics.get_meter("story_slicer")
        self._session_duration = meter.create_histogram(
            "story_slicer.session.duration", unit="s"
        )
        self._attempt_duration = meter.create_histogram(
            "story_slicer.attempt.duration", unit="s"
        )
        self._sessions_count = meter.create_counter("story_slicer.sessions")
        self._schema_failures = meter.create_counter("story_slicer.schema_failures")
        self._repairs = meter.create_counter("story_slicer.repairs")
        self._tokens = meter.create_counter("story_slicer.tokens", unit="{token}")
        self._alerts = meter.create_counter("story_slicer.alerts")
        self._sessions: dict[str, tuple[Span, SessionContext]] = {}
        self._closed = False

    @classmethod
    def from_settings(cls, settings: RuntimeSettings) -> OpenTelemetryObservability:
        """Construct local providers; export over HTTP only when opted in."""
        if settings.otel_export_mode == "disabled":
            return cls(
                TracerProvider(shutdown_on_exit=False),
                MeterProvider(shutdown_on_exit=False),
            )
        endpoint = str(settings.otel_exporter_otlp_endpoint).rstrip("/")
        resource = Resource({"service.name": settings.otel_service_name})
        timeout = settings.otel_export_timeout_seconds
        traces = TracerProvider(resource=resource, shutdown_on_exit=False)
        traces.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=endpoint + "/v1/traces",
                    timeout=timeout,
                    headers={},
                    compression=Compression.NoCompression,
                ),
                schedule_delay_millis=settings.otel_export_interval_seconds * 1000,
                export_timeout_millis=timeout * 1000,
            )
        )
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(
                endpoint=endpoint + "/v1/metrics",
                timeout=timeout,
                headers={},
                compression=Compression.NoCompression,
            ),
            export_interval_millis=settings.otel_export_interval_seconds * 1000,
            export_timeout_millis=timeout * 1000,
        )
        metrics = MeterProvider(
            resource=resource, metric_readers=[reader], shutdown_on_exit=False
        )
        return cls(traces, metrics)

    def start_session(self, context: SessionContext) -> SessionHandle:
        handle = SessionHandle(session_id=str(uuid4()))
        if self._closed:
            return handle
        try:
            span = self._tracer.start_span(
                "story_slicer.session",
                attributes={
                    "provider": context.provider,
                    "model": context.model,
                },
            )
            span.add_event("session_started")
        except Exception:
            _LOGGER.warning("Telemetry session start failed")
            span = NonRecordingSpan(INVALID_SPAN_CONTEXT)
        self._sessions[handle.session_id] = (span, context)
        return handle

    def record(self, event: ObservabilityEvent) -> None:
        session = self._sessions.get(event.session.session_id)
        if session is None:
            return
        try:
            self._record(event, session)
        except Exception:
            _LOGGER.warning("Telemetry event recording failed")
        finally:
            if isinstance(event, SessionCompleted):
                self._sessions.pop(event.session.session_id, None)
                try:
                    session[0].end()
                except Exception:
                    _LOGGER.warning("Telemetry session completion failed")

    def _record(
        self, event: ObservabilityEvent, session: tuple[Span, SessionContext]
    ) -> None:
        span, context = session
        labels = {"provider": context.provider}
        attributes: dict[str, str | int | float | bool] = {
            name: value
            for name, value in event.model_dump().items()
            if name not in {"session", "context", "usage"}
            and isinstance(value, str | int | float | bool)
        }
        span.add_event(event.kind, attributes=attributes)
        if isinstance(event, AttemptCompleted):
            self._attempt_duration.record(event.elapsed_seconds, labels)
            end = time_ns()
            child = self._tracer.start_span(
                "story_slicer.attempt",
                context=set_span_in_context(span),
                start_time=end - int(event.elapsed_seconds * 1_000_000_000),
                attributes={"attempt": event.attempt},
            )
            child.end(end_time=end)
        elif isinstance(event, SchemaFailure):
            self._schema_failures.add(
                1, labels | {"classification": event.classification}
            )
        elif isinstance(event, RepairScheduled):
            self._repairs.add(1, labels)
        elif isinstance(event, OperationalAlert | CriticalAlert):
            self._alerts.add(1, labels | {"severity": event.severity})
        elif isinstance(event, SessionCompleted):
            self._session_duration.record(
                event.elapsed_seconds, labels | {"outcome": event.outcome}
            )
            self._sessions_count.add(1, labels | {"outcome": event.outcome})
            span.set_attribute("usage_complete", event.usage_complete)
            span.set_attribute("outcome", event.outcome)
            span.set_status(
                StatusCode.OK if event.outcome == "success" else StatusCode.ERROR
            )
            for direction, count in [
                ("input", event.usage.input_tokens),
                ("output", event.usage.output_tokens),
            ]:
                if count is not None:
                    self._tokens.add(count, labels | {"direction": direction})

    def close(self) -> None:
        """End unfinished sessions and flush/shut down providers; safe to repeat."""
        if self._closed:
            return
        self._closed = True
        sessions, self._sessions = self._sessions, {}
        for span, _ in sessions.values():
            try:
                span.set_attribute("outcome", "cancelled")
                span.set_status(StatusCode.ERROR)
                span.end()
            except Exception:
                _LOGGER.warning("Telemetry session shutdown failed")
        for provider in (self._traces, self._metrics):
            try:
                provider.force_flush()
            except Exception:
                _LOGGER.warning("Telemetry flush failed")
            try:
                provider.shutdown()
            except Exception:
                _LOGGER.warning("Telemetry shutdown failed")
