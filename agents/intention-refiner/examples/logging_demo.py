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
                    "tag": "MISSING_INFO",
                    "text": "Identify the intended customer group.",
                }
            ],
            "audit": {
                "ambiguities": [],
                "missing_information": ["target"],
                "metric_gaps": [],
                "other_risks": [],
            },
            "refinement_proposals": [
                {
                    "field_name": "target",
                    "proposed_text": "Customers booking online.",
                    "rationale": "The intended users were not specified.",
                }
            ],
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
