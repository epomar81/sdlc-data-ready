"""Run a local refinement with deterministic model output to see console logs."""

import json

from intention_refiner.application.ports import ModelResponse
from intention_refiner.application.refine import RefineInitiative
from intention_refiner.console_logging import configure_logging


class DemoModel:
    def generate(self, prompt: str) -> ModelResponse:
        response = {
            "initiative": {"title": "Online booking"},
            "suggestions": [
                {
                    "field_name": "target",
                    "tag": "AI_ENHANCED",
                    "text": "[IA ENHANCED] Intended audience: customers booking services online.",
                }
            ],
            "audit": {
                "ambiguities": [],
                "missing_information": [],
                "other_risks": [],
            },
        }
        return ModelResponse(
            text=json.dumps(response),
            prompt_tokens=120,
            completion_tokens=45,
            total_tokens=165,
        )


if __name__ == "__main__":
    configure_logging()
    RefineInitiative(DemoModel()).execute("Build an online booking service")
