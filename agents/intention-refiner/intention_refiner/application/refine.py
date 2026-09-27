import json
import time
from importlib.resources import files

from pydantic import ValidationError

from intention_refiner.application.ports import ModelPort
from intention_refiner.domain.models import RefinementPayload, RefinementResult


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
        payload = parse_response(response)
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
