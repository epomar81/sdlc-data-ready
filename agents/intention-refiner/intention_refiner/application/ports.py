from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ModelResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ModelPort(Protocol):
    def generate(self, prompt: str) -> ModelResponse: ...
