"""Bounded self-healing orchestration using only domain models and ports."""

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal

from pydantic import ValidationError

from story_slicer.application.prompts import REPAIR_INSTRUCTIONS, SLICING_INSTRUCTIONS
from story_slicer.application.validation import validate_stories
from story_slicer.domain.models import RequirementDocument, StoryBatch
from story_slicer.ports.configuration import ConfigurationPort
from story_slicer.ports.errors import (
    InputError,
    ProviderError,
    SessionTimeoutError,
    ValidationExhaustedError,
)
from story_slicer.ports.filesystem import FileReadRequest, FileSystemPort
from story_slicer.ports.llm import (
    GenerationRequest,
    GenerationResult,
    LLMPort,
    RepairFeedback,
    TokenUsage,
)
from story_slicer.ports.observability import (
    AttemptCompleted,
    CriticalAlert,
    ObservabilityPort,
    OperationalAlert,
    RepairScheduled,
    SchemaFailure,
    SessionCompleted,
    SessionContext,
    SessionHandle,
    SessionOutcome,
)
from story_slicer.ports.requirements import RequirementParserPort, RequirementSource


@dataclass(frozen=True, slots=True, kw_only=True)
class SlicingDependencies:
    configuration: ConfigurationPort
    filesystem: FileSystemPort
    parser: RequirementParserPort
    llm: LLMPort
    observability: ObservabilityPort


@dataclass(slots=True, kw_only=True)
class _UsageTotals:
    input_tokens: int | None = None
    output_tokens: int | None = None
    complete: bool = True

    def add(self, usage: TokenUsage) -> None:
        if usage.input_tokens is not None:
            self.input_tokens = (self.input_tokens or 0) + usage.input_tokens
        if usage.output_tokens is not None:
            self.output_tokens = (self.output_tokens or 0) + usage.output_tokens
        if usage.input_tokens is None or usage.output_tokens is None:
            self.complete = False

    def snapshot(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens, output_tokens=self.output_tokens
        )


@dataclass(slots=True, kw_only=True)
class _Session:
    handle: SessionHandle
    attempts: int = 0
    responses: int = 0
    failures: int = 0
    alerted: bool = False
    outcome: SessionOutcome = "aborted"
    usage: _UsageTotals = field(default_factory=_UsageTotals)


class SliceRequirement:
    def __init__(self, dependencies: SlicingDependencies) -> None:
        self._ports = dependencies
        self._settings = dependencies.configuration.load()

    async def execute(self, path: str) -> StoryBatch:
        try:
            source = RequirementSource(path=path)
        except ValidationError:
            raise InputError(
                "An explicit nonblank requirement file path is required"
            ) from None
        try:
            content = await asyncio.wait_for(
                self._ports.filesystem.read(
                    FileReadRequest(
                        path=source.path,
                        max_bytes=self._settings.max_input_bytes,
                    )
                ),
                timeout=self._settings.session_timeout_seconds,
            )
        except TimeoutError:
            raise SessionTimeoutError("Requirement file read timed out") from None
        started = perf_counter()
        handle = self._ports.observability.start_session(
            SessionContext(
                provider=self._settings.provider,
                model=self._settings.model,
            )
        )
        session = _Session(handle=handle)
        try:
            async with asyncio.timeout(self._settings.session_timeout_seconds):
                requirement = self._ports.parser.parse(content)
                result = await self._slice(requirement, session)
            session.outcome = "success"
            return result
        except InputError:
            session.outcome = "invalid_input"
            raise
        except ProviderError:
            session.outcome = "provider_failure"
            raise
        except SessionTimeoutError:
            session.outcome = "timeout"
            raise
        except TimeoutError:
            session.outcome = "timeout"
            raise SessionTimeoutError(
                "Story slicing reached the session timeout of "
                f"{self._settings.session_timeout_seconds:g}s; "
                "adjust STORY_SLICER_SESSION_TIMEOUT_SECONDS"
            ) from None
        except asyncio.CancelledError:
            session.outcome = "cancelled"
            raise
        finally:
            usage = session.usage.snapshot()
            self._ports.observability.record(
                SessionCompleted(
                    session=handle,
                    outcome=session.outcome,
                    elapsed_seconds=perf_counter() - started,
                    usage=usage,
                    usage_complete=session.usage.complete
                    and usage.input_tokens is not None
                    and usage.output_tokens is not None,
                )
            )

    async def _attempt(
        self, request: GenerationRequest, session: _Session
    ) -> GenerationResult:
        session.attempts += 1
        started = perf_counter()
        usage = TokenUsage()
        try:
            async with asyncio.timeout(self._settings.request_timeout_seconds):
                result = await self._ports.llm.generate(request)
            session.responses += 1
            usage = result.usage
            return result
        except TimeoutError, SessionTimeoutError:
            raise SessionTimeoutError(
                f"LLM attempt {session.attempts} reached the request timeout of "
                f"{self._settings.request_timeout_seconds:g}s; "
                "adjust STORY_SLICER_REQUEST_TIMEOUT_SECONDS"
            ) from None
        finally:
            session.usage.add(usage)
            self._ports.observability.record(
                AttemptCompleted(
                    session=session.handle,
                    attempt=session.attempts,
                    elapsed_seconds=perf_counter() - started,
                    usage=usage,
                )
            )

    async def _slice(
        self, requirement: RequirementDocument, session: _Session
    ) -> StoryBatch:
        feedback: RepairFeedback | None = None
        while True:
            instructions = SLICING_INSTRUCTIONS
            if feedback is not None:
                instructions += "\n" + REPAIR_INSTRUCTIONS
            response = await self._attempt(
                GenerationRequest(
                    instructions=instructions,
                    requirement=requirement,
                    json_schema=StoryBatch.model_json_schema(),
                    repair_feedback=feedback,
                ),
                session,
            )
            classification: Literal["schema", "parsing"]
            try:
                return validate_stories(response.text, requirement.project)
            except ValidationError as error:
                classification = "schema"
                diagnostic = str(error)
            except (ValueError, RecursionError) as error:
                classification = "parsing"
                diagnostic = str(error)
            session.failures += 1
            self._ports.observability.record(
                SchemaFailure(
                    session=session.handle,
                    attempt=session.attempts,
                    classification=classification,
                )
            )
            self._alert_if_unstable(session)
            if session.attempts >= 1 + self._settings.max_retries:
                self._ports.observability.record(
                    CriticalAlert(
                        session=session.handle,
                        attempts=session.attempts,
                    )
                )
                raise ValidationExhaustedError(
                    f"Story validation failed after {session.attempts} attempts"
                )
            feedback = RepairFeedback(
                previous_response=response.text, diagnostic=diagnostic
            )
            self._ports.observability.record(
                RepairScheduled(
                    session=session.handle,
                    attempt=session.attempts + 1,
                )
            )

    def _alert_if_unstable(self, session: _Session) -> None:
        rate = session.failures / session.responses
        if (
            not session.alerted
            and session.responses >= self._settings.schema_error_min_attempts
            and rate >= self._settings.schema_error_rate_threshold
        ):
            session.alerted = True
            self._ports.observability.record(
                OperationalAlert(
                    session=session.handle,
                    attempts=session.attempts,
                    schema_error_rate=rate,
                )
            )
