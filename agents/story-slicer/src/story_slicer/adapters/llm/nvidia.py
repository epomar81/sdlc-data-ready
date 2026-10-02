"""NVIDIA chat-completions REST adapter."""

import httpx
from pydantic import ValidationError

from story_slicer.adapters.llm.http import (
    HTTPModelAdapter,
    system_instruction,
    user_content,
)
from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import ConfigurationError, ProviderError
from story_slicer.ports.llm import GenerationRequest, GenerationResult, TokenUsage


class NvidiaAdapter(HTTPModelAdapter):
    def __init__(
        self, settings: RuntimeSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        if (
            settings.provider != "nvidia"
            or settings.nvidia_base_url is None
            or settings.nvidia_api_key is None
        ):
            raise ConfigurationError(
                "NVIDIA requires matching provider settings, endpoint, and credentials"
            )
        super().__init__(settings, client)
        self._url = str(settings.nvidia_base_url).rstrip("/") + "/chat/completions"
        self._headers = {
            "Authorization": "Bearer " + settings.nvidia_api_key.get_secret_value()
        }

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        body = await self._post(
            {
                "model": self._settings.model,
                "messages": [
                    {"role": "system", "content": system_instruction(request)},
                    {"role": "user", "content": user_content(request)},
                ],
                "stream": False,
            }
        )
        try:
            text = body["choices"][0]["message"]["content"]
            usage = body.get("usage", {})
            return GenerationResult(
                text=text,
                usage=TokenUsage.model_validate(
                    {
                        "input_tokens": usage.get("prompt_tokens"),
                        "output_tokens": usage.get("completion_tokens"),
                    }
                ),
            )
        except KeyError, IndexError, TypeError, AttributeError, ValidationError:
            raise ProviderError(
                "NVIDIA returned an invalid response envelope"
            ) from None
