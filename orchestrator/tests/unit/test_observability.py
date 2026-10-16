from types import SimpleNamespace

from orchestrator.infrastructure.observability import OpenTelemetryBatchObservability


def test_batch_telemetry_records_histograms_and_alert_events(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORT_MODE", "disabled")
    telemetry = OpenTelemetryBatchObservability()
    story_count = []
    ambiguity = []
    alerts = []
    spans = []
    class Histogram:
        def __init__(self, values: list) -> None:
            self._values = values

        def record(self, value: object) -> None:
            self._values.append(value)

    class Counter:
        def add(self, value: int, attributes: dict) -> None:
            alerts.append((value, attributes))

    class SpanContext:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def add_event(self, name, attributes):
            spans.append((name, attributes))

    class Tracer:
        def start_as_current_span(self, name: str) -> SpanContext:
            return SpanContext()

    telemetry._story_count = Histogram(story_count)
    telemetry._ambiguity_score = Histogram(ambiguity)
    telemetry._alerts = Counter()
    telemetry._tracer = Tracer()
    batch = SimpleNamespace(
        story_count=2,
        ambiguity_score=0.25,
        alerts=[SimpleNamespace(severity="WARNING", rationale="Clarify the actor.")],
    )

    telemetry.record_batch(batch)

    assert story_count == [2]
    assert ambiguity == [0.25]
    assert alerts == [(1, {"severity": "WARNING"})]
    assert spans == [
        (
            "story_batch.alert",
            {"severity": "WARNING", "rationale": "Clarify the actor."},
        )
    ]
    telemetry.close()
