import json
import logging
import time
from importlib.resources import files

from pydantic import ValidationError

from intention_refiner.application.ports import ModelPort
from intention_refiner.domain.models import RefinementPayload, RefinementResult

logger = logging.getLogger(__name__)

TAG_REASONS = {
    "MISSING_INFO": "required information is missing",
    "AI_ENHANCED": "the content was strengthened for clarity or completeness",
    "FEATURE_IDEA": "the content proposes a new feature idea",
    "CLARIFICATION": "the content asks to resolve ambiguity",
}


class InvalidModelResponse(ValueError):
    """The model returned data outside the expected report contract."""


class RefineInitiative:
    def __init__(self, model: ModelPort):
        self.model = model

    def execute(self, text: str) -> RefinementResult:
        if not text.strip():
            raise ValueError("Input file is empty")
        instructions = files("intention_refiner").joinpath("requirements_prompt.md").read_text(encoding="utf-8")
        prompt = f"{instructions}\n\nINITIATIVE TEXT:\n{text}"
        start = time.perf_counter()
        response = self.model.generate(prompt)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Token usage: Prompt tokens: %d, Completion tokens: %d, Total tokens: %d",
            response.prompt_tokens, response.completion_tokens, response.total_tokens,
        )
        payload = parse_response(response.text)
        for suggestion in payload.suggestions:
            logger.info(
                "Generated tag: %s | Content: %s | Reason: %s",
                suggestion.tag, suggestion.text, TAG_REASONS[suggestion.tag],
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
