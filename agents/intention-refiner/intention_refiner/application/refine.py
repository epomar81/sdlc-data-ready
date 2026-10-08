import json
import logging
import time
from contextlib import nullcontext
from importlib.resources import files

from pydantic import ValidationError

from intention_refiner.application.ports import ModelPort
from intention_refiner.domain.models import RefinementPayload, RefinementResult
from intention_refiner.telemetry import ModelRequestMetrics, Telemetry, record_exception

logger = logging.getLogger(__name__)

class InvalidModelResponse(ValueError):
    """The model returned data outside the expected report contract."""


class RefineInitiative:
    def __init__(self, model: ModelPort, telemetry: Telemetry | None = None):
        self.model = model
        self.telemetry = telemetry

    def execute(self, text: str) -> RefinementResult:
        if not text.strip():
            raise ValueError("Input file is empty")
        instructions = files("intention_refiner").joinpath("requirements_prompt.md").read_text(encoding="utf-8")
        prompt = f"{instructions}\n\nINITIATIVE TEXT:\n{text}"
        start = time.perf_counter()
        model_name = getattr(getattr(self.model, "config", None), "model", "unknown")
        provider = type(self.model).__name__.removesuffix("Adapter").lower()
        span_context = (
            self.telemetry.span("model.request", {"provider": provider, "model": model_name})
            if self.telemetry
            else nullcontext(None)
        )
        span = None
        try:
            with span_context as span:
                response = self.model.generate(prompt)
        except Exception as exc:
            elapsed_seconds = time.perf_counter() - start
            if span is not None:
                record_exception(span, exc)
            if self.telemetry:
                self.telemetry.record_model_request(
                    ModelRequestMetrics(provider, model_name, elapsed_seconds, False)
                )
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000
        if self.telemetry:
            self.telemetry.record_model_request(
                ModelRequestMetrics(
                    provider, model_name, elapsed_ms / 1000, True,
                    response.prompt_tokens, response.completion_tokens, response.total_tokens,
                )
            )
        logger.info(
            "Model request completed",
            extra={
                "event": "model_request_completed",
                "duration_ms": elapsed_ms,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
            },
        )
        payload = parse_response(response.text)
        for proposal in payload.refinement_proposals:
            logger.info(
                "Refinement proposal created",
                extra={
                    "event": "refinement_proposal_created",
                    "duration_ms": elapsed_ms,
                    "field_name": proposal.field_name,
                },
            )
        return RefinementResult(**payload.model_dump(), response_time_ms=elapsed_ms)


def parse_response(response: str) -> RefinementPayload:
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise InvalidModelResponse("Model returned an incomplete JSON code block")
        text = "\n".join(lines[1:-1])
    try:
        data = json.loads(text)
        return RefinementPayload.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise InvalidModelResponse("Model returned invalid requirements JSON") from exc
