from collections.abc import Sequence

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, Sum
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from story_slicer.adapters.observability.opentelemetry import OpenTelemetryObservability
from story_slicer.ports.llm import TokenUsage
from story_slicer.ports.observability import (
    AttemptCompleted,
    CriticalAlert,
    OperationalAlert,
    RepairScheduled,
    SchemaFailure,
    SessionCompleted,
    SessionContext,
)


def test_telemetry_records_metrics_spans_and_alerts() -> None:
    exporter = InMemorySpanExporter()
    traces = TracerProvider()
    traces.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    metrics = MeterProvider(metric_readers=[reader])
    telemetry = OpenTelemetryObservability(traces, metrics)
    session = telemetry.start_session(
        SessionContext(provider="gemini", model="test-model")
    )
    telemetry.record(
        AttemptCompleted(
            session=session, attempt=1, elapsed_seconds=0.1, usage=TokenUsage()
        )
    )
    telemetry.record(SchemaFailure(session=session, attempt=1, classification="schema"))
    telemetry.record(RepairScheduled(session=session, attempt=2))
    telemetry.record(
        OperationalAlert(session=session, attempts=1, schema_error_rate=1.0)
    )
    telemetry.record(CriticalAlert(session=session, attempts=2))
    telemetry.record(
        SessionCompleted(
            session=session,
            outcome="aborted",
            elapsed_seconds=0.2,
            usage=TokenUsage(input_tokens=4, output_tokens=8),
            usage_complete=False,
        )
    )
    spans = exporter.get_finished_spans()
    parent = next(span for span in spans if span.name == "story_slicer.session")
    child = next(span for span in spans if span.name == "story_slicer.attempt")
    assert child.parent is not None and parent.context is not None
    assert child.parent.span_id == parent.context.span_id
    assert {event.name for event in parent.events} >= {
        "session_started",
        "operational_alert",
        "critical_alert",
    }
    data = reader.get_metrics_data()
    assert data is not None
    instruments = {
        metric.name: metric
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
    for name in ["story_slicer.repairs", "story_slicer.schema_failures"]:
        counter = instruments[name].data
        assert isinstance(counter, Sum)
        assert counter.data_points[0].value == 1
    tokens = instruments["story_slicer.tokens"].data
    assert isinstance(tokens, Sum)
    assert {
        point.attributes["direction"]: point.value
        for point in tokens.data_points
        if point.attributes is not None
    } == {"input": 4, "output": 8}
    for metric in instruments.values():
        for point in metric.data.data_points:
            assert point.attributes is not None
            assert "session_id" not in point.attributes
    telemetry.close()


class FailingExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        raise RuntimeError("Exporter unavailable")

    def shutdown(self) -> None:
        pass


def test_telemetry_export_failure_does_not_escape() -> None:
    traces = TracerProvider()
    traces.add_span_processor(SimpleSpanProcessor(FailingExporter()))
    telemetry = OpenTelemetryObservability(traces, MeterProvider())
    session = telemetry.start_session(
        SessionContext(provider="nvidia", model="test-model")
    )
    telemetry.record(
        SessionCompleted(
            session=session,
            outcome="success",
            elapsed_seconds=1.0,
            usage=TokenUsage(),
            usage_complete=False,
        )
    )
    telemetry.close()


def test_local_telemetry_does_not_construct_network_exporters() -> None:
    from unittest.mock import patch

    from story_slicer.ports.configuration import RuntimeSettings
    from tests.fixtures import settings_data

    settings = RuntimeSettings.model_validate(settings_data())
    with (
        patch(
            "story_slicer.adapters.observability.opentelemetry.OTLPSpanExporter"
        ) as traces,
        patch(
            "story_slicer.adapters.observability.opentelemetry.OTLPMetricExporter"
        ) as metrics,
    ):
        telemetry = OpenTelemetryObservability.from_settings(settings)
        telemetry.close()
    traces.assert_not_called()
    metrics.assert_not_called()


def test_otlp_export_is_explicitly_enabled() -> None:
    from unittest.mock import patch

    from story_slicer.ports.configuration import RuntimeSettings
    from tests.fixtures import settings_data

    settings = RuntimeSettings.model_validate(
        settings_data() | {"otel_export_mode": "otlp"}
    )
    with (
        patch(
            "story_slicer.adapters.observability.opentelemetry.OTLPSpanExporter"
        ) as traces,
        patch(
            "story_slicer.adapters.observability.opentelemetry.OTLPMetricExporter"
        ) as metrics,
    ):
        telemetry = OpenTelemetryObservability.from_settings(settings)
        telemetry.close()
    traces.assert_called_once()
    metrics.assert_called_once()
