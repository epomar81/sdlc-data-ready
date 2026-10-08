from unittest.mock import patch

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from intention_refiner.telemetry import (
    PublicationMetrics,
    PublicationPayloadMetrics,
    Telemetry,
)


def test_metrics_exporter_default_console_and_flush():
    with (
        patch("intention_refiner.telemetry.MeterProvider") as provider,
        patch("intention_refiner.telemetry.ConsoleMetricExporter") as exporter,
    ):
        telemetry = Telemetry(False)
        exporter.assert_called_once()
        assert "out" in exporter.call_args.kwargs
        telemetry.shutdown()
        provider.return_value.force_flush.assert_called_once()
        provider.return_value.shutdown.assert_called_once()


def test_metrics_have_bounded_attributes_and_correct_values():
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    with patch("intention_refiner.telemetry.MeterProvider", return_value=provider):
        telemetry = Telemetry(False)
    telemetry.record_publication(PublicationMetrics("github", True))
    telemetry.record_publication(PublicationMetrics("jira", False, "timeout"))
    telemetry.record_publication_payload(
        PublicationPayloadMetrics("github", "result", len("café".encode()))
    )
    scopes = reader.get_metrics_data().resource_metrics[0].scope_metrics
    scope = next(
        scope for scope in scopes if scope.scope.name == "agent.integration.metrics"
    )
    instruments = {metric.name: metric for metric in scope.metrics}
    assert instruments["publications_success_total"].data.data_points[0].value == 1
    failed = instruments["publications_failed_total"].data.data_points[0]
    assert failed.value == 1
    assert failed.attributes == {"provider": "jira", "reason": "timeout"}
    payload = instruments["publication_payload_bytes"].data.data_points[0]
    assert payload.count == 1 and payload.sum == 5
    assert payload.attributes == {"provider": "github", "operation": "result"}
    telemetry.shutdown()


def test_metrics_export_failures_do_not_propagate():
    with patch("intention_refiner.telemetry.MeterProvider") as provider:
        telemetry = Telemetry(False)
        provider.return_value.force_flush.side_effect = RuntimeError("unavailable")
        provider.return_value.shutdown.side_effect = RuntimeError("unavailable")
        telemetry.shutdown()


def test_span_never_records_exception_body():
    with (
        patch("intention_refiner.telemetry.MeterProvider"),
        patch("intention_refiner.telemetry.trace.get_tracer") as tracer,
    ):
        telemetry = Telemetry(False)
        try:
            with telemetry.span("source.read", {"provider": "github"}):
                raise ValueError("private content")
        except ValueError:
            pass
        kwargs = tracer.return_value.start_as_current_span.call_args.kwargs
        assert kwargs["record_exception"] is False
        assert kwargs["set_status_on_exception"] is False
        span = tracer.return_value.start_as_current_span.return_value.__enter__.return_value
        span.set_status.assert_called_once()
        assert span.set_status.call_args.args[0].description == "ValueError"


def test_otlp_selection_does_not_enable_trace_export():
    with (
        patch("intention_refiner.telemetry.MeterProvider"),
        patch("intention_refiner.telemetry.OTLPMetricExporter") as exporter,
        patch("intention_refiner.telemetry.TracerProvider") as traces,
    ):
        telemetry = Telemetry(False, "otlp")
        exporter.assert_called_once()
        traces.assert_not_called()
        telemetry.shutdown()
