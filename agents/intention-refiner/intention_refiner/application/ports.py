from typing import Protocol


class ModelPort(Protocol):
    def generate(self, prompt: str) -> str: ...
