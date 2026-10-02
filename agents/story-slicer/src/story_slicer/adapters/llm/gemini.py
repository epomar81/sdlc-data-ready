"""Gemini generateContent REST adapter."""

from urllib.parse import quote

import httpx

from story_slicer.adapters.llm.http import (
    HTTPModelAdapter,
    system_instruction,
    user_content,
)
from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import ConfigurationError, ProviderError
from story_slicer.ports.llm import GenerationRequest, GenerationResult, TokenUsage


class GeminiAdapter(HTTPModelAdapter):
    def __init__(
        self, settings: RuntimeSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        if (
            settings.provider != "gemini"
            or settings.gemini_base_url is None
            or settings.gemini_api_key is None
        ):
            raise ConfigurationError(
                "Gemini requires matching provider settings, endpoint, and credentials"
            )
        if settings.gemini_base_url.host == "aistudio.google.com":
            raise ConfigurationError(
                "STORY_SLICER_GEMINI_BASE_URL points to an AI Studio web page. "
                "Use https://generativelanguage.googleapis.com/v1beta"
            )
        super().__init__(settings, client)
        model = quote(settings.model.removeprefix("models/"), safe="")
        base_url = str(settings.gemini_base_url).rstrip("/")
        self._url = f"{base_url}/models/{model}:generateContent"
        self._headers = {"x-goog-api-key": settings.gemini_api_key.get_secret_value()}

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        body = await self._post(
            {
                "systemInstruction": {"parts": [{"text": system_instruction(request)}]},
                "contents": [
                    {"role": "user", "parts": [{"text": user_content(request)}]}
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": request.json_schema,
                },
            }
        )
        try:
            parts = body["candidates"][0]["content"]["parts"]
            if not isinstance(parts, list):
                raise ValueError("Invalid content parts")
            text = "".join(
                part["text"] for part in parts if not part.get("thought", False)
            )
            usage = body.get("usageMetadata", {})
            counts = TokenUsage.model_validate(
                {
                    "input_tokens": usage.get("promptTokenCount"),
                    "output_tokens": usage.get("candidatesTokenCount"),
                }
            )
            thoughts = TokenUsage.model_validate(
                {"output_tokens": usage.get("thoughtsTokenCount")}
            )
            output_tokens = counts.output_tokens
            if output_tokens is not None and thoughts.output_tokens is not None:
                output_tokens += thoughts.output_tokens
            return GenerationResult(
                text=text,
                usage=TokenUsage(
                    input_tokens=counts.input_tokens,
                    output_tokens=output_tokens,
                ),
            )
        except (
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            ValueError,
        ):
            raise ProviderError(
                "Gemini returned an invalid or blocked response envelope"
            ) from None
