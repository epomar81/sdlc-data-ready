"""Typed telemetry events with no OpenTelemetry dependency or raw prompts."""

from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, model_validator

from story_slicer.domain.models import NonBlank
from story_slicer.ports.contracts import (
    ContractModel,
    ElapsedSeconds,
    ErrorRate,
    PositiveInteger,
    Provider,
)
from story_slicer.ports.llm import TokenUsage

SessionOutcome = Literal[
    "success", "invalid_input", "provider_failure", "timeout", "aborted", "cancelled"
]


class SessionContext(ContractModel):
    provider: Provider
    model: NonBlank


class SessionHandle(ContractModel):
    session_id: NonBlank


class SessionEvent(ContractModel):
    session: SessionHandle


class SessionStarted(SessionEvent):
    kind: Literal["session_started"] = "session_started"
    context: SessionContext


class AttemptCompleted(SessionEvent):
    kind: Literal["attempt_completed"] = "attempt_completed"
    attempt: PositiveInteger
    elapsed_seconds: ElapsedSeconds
    usage: TokenUsage


class SchemaFailure(SessionEvent):
    kind: Literal["schema_failure"] = "schema_failure"
    attempt: PositiveInteger
    classification: Literal["parsing", "schema"]


class RepairScheduled(SessionEvent):
    kind: Literal["repair_scheduled"] = "repair_scheduled"
    attempt: PositiveInteger


class OperationalAlert(SessionEvent):
    kind: Literal["operational_alert"] = "operational_alert"
    severity: Literal["warning"] = "warning"
    attempts: PositiveInteger
    schema_error_rate: ErrorRate


class CriticalAlert(SessionEvent):
    kind: Literal["critical_alert"] = "critical_alert"
    severity: Literal["critical"] = "critical"
    reason: Literal["unstable_llm"] = "unstable_llm"
    attempts: PositiveInteger


class SessionCompleted(SessionEvent):
    kind: Literal["session_completed"] = "session_completed"
    outcome: SessionOutcome
    elapsed_seconds: ElapsedSeconds
    usage: TokenUsage
    usage_complete: bool

    @model_validator(mode="after")
    def validate_complete_usage(self) -> Self:
        if self.usage_complete and (
            self.usage.input_tokens is None or self.usage.output_tokens is None
        ):
            raise ValueError(
                "Complete usage requires known input and output token counts"
            )
        return self


ObservabilityEvent = Annotated[
    SessionStarted
    | AttemptCompleted
    | SchemaFailure
    | RepairScheduled
    | OperationalAlert
    | CriticalAlert
    | SessionCompleted,
    Field(discriminator="kind"),
]


class ObservabilityPort(Protocol):
    def start_session(self, context: SessionContext) -> SessionHandle:
        """Start timing, record SessionStarted, and return an opaque session handle."""
        ...

    def record(self, event: ObservabilityEvent) -> None:
        """Record an event; implementations must isolate telemetry export failures."""
        ...
