import json
import logging
import re
import time
from contextlib import nullcontext
from importlib.resources import files

from pydantic import ValidationError

from intention_refiner.application.ports import ModelPort
from intention_refiner.domain.models import (
    RefinementPayload,
    RefinementResult,
    Suggestion,
)
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
        for suggestion in payload.suggestions:
            logger.info(
                "Suggestion created",
                extra={
                    "event": "suggestion_created",
                    "duration_ms": elapsed_ms,
                    "field_name": suggestion.field_name,
                    "tag": suggestion.tag,
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
        payload = RefinementPayload.model_validate(data)
        return normalize_payload(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise InvalidModelResponse("Model returned invalid requirements JSON") from exc


def normalize_payload(payload: RefinementPayload) -> RefinementPayload:
    """Remove repeated report content and turn ambiguity notes into questions."""
    initiative = payload.initiative.model_dump()
    seen: set[str] = set()
    for field_name, value in initiative.items():
        if not isinstance(value, str):
            continue
        paragraphs = []
        for paragraph in re.split(r"\n\s*\n", value.strip()):
            normalized = _normalize_text(paragraph)
            if normalized and normalized not in seen:
                seen.add(normalized)
                paragraphs.append(paragraph.strip())
        initiative[field_name] = "\n\n".join(paragraphs) or None

    suggestions = list(payload.suggestions)
    for ambiguity in payload.audit.ambiguities:
        question = ambiguity.strip()
        if not question.endswith(("?", "؟")):
            detail = question.rstrip(".!")
            question = (
                f"¿Podrías aclarar esto: {detail}?"
                if any(character in detail.casefold() for character in "áéíóúñ¿")
                else f"Could you clarify: {detail}?"
            )
        suggestions.append(
            Suggestion(field_name=_ambiguity_field(ambiguity), tag="CLARIFICATION", text=question)
        )

    initiative_text = " ".join(
        value for value in initiative.values() if isinstance(value, str) and value
    )
    initiative_normalized = _normalize_text(initiative_text)
    suggestions = [
        item for item in suggestions
        if not (
            item.field_name == "kpi"
            and _normalize_text(item.text) in initiative_normalized
        )
    ]
    return RefinementPayload(
        initiative=initiative,
        suggestions=suggestions,
        audit=payload.audit.model_copy(update={"ambiguities": [], "missing_information": []}),
    )


def _normalize_text(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def _ambiguity_field(value: str) -> str:
    text = value.casefold()
    if any(word in text for word in ("metric", "kpi", "baseline", "threshold", "métrica", "indicador")):
        return "kpi"
    if any(word in text for word in ("user", "customer", "audience", "target", "usuario", "público", "cliente")):
        return "target"
    if any(word in text for word in ("scope", "include", "exclude", "permission", "public", "private", "alcance", "permiso", "públic", "privad")):
        return "business_scope"
    return "problem_statement"
