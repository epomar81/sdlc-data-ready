"""OpenAI Responses REST adapter with JSON mode and application validation."""

import httpx

from story_slicer.adapters.llm.http import (
    HTTPModelAdapter,
    system_instruction,
    user_content,
)
from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import ConfigurationError, ProviderError
from story_slicer.ports.llm import GenerationRequest, GenerationResult, TokenUsage


class OpenAIAdapter(HTTPModelAdapter):
    def __init__(
        self, settings: RuntimeSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        if (
            settings.provider != "openai"
            or settings.openai_base_url is None
            or settings.openai_api_key is None
        ):
            raise ConfigurationError(
                "OpenAI requires matching provider settings, endpoint, and credentials"
            )
        super().__init__(settings, client)
        self._url = str(settings.openai_base_url).rstrip("/") + "/responses"
        self._headers = {
            "Authorization": "Bearer " + settings.openai_api_key.get_secret_value()
        }

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        body = await self._post(
            {
                "model": self._settings.model,
                "instructions": system_instruction(request),
                "input": user_content(request),
                "text": {"format": {"type": "json_object"}},
                "store": False,
            }
        )
        try:
            if body["status"] != "completed" or not isinstance(body["output"], list):
                raise ValueError("Response is incomplete or invalid")
            parts: list[str] = []
            for item in body["output"]:
                if item["type"] != "message":
                    continue
                if not isinstance(item["content"], list):
                    raise ValueError("Invalid message content")
                for part in item["content"]:
                    if part["type"] == "refusal":
                        raise ValueError("Response refused")
                    if part["type"] == "output_text":
                        text = part["text"]
                        if not isinstance(text, str):
                            raise ValueError("Invalid output text")
                        parts.append(text)
            text = "".join(parts)
            if not text.strip():
                raise ValueError("Response has no output text")
            usage = body.get("usage") or {}
            return GenerationResult(
                text=text,
                usage=TokenUsage.model_validate(
                    {
                        "input_tokens": usage.get("input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                    }
                ),
            )
        except KeyError, TypeError, AttributeError, ValueError:
            raise ProviderError(
                "OpenAI returned an invalid, incomplete, or refused response envelope"
            ) from None
