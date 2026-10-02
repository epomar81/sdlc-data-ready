"""Shared HTTP transport and provider-independent request formatting."""

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import ProviderError, SessionTimeoutError
from story_slicer.ports.llm import GenerationRequest, GenerationResult


def system_instruction(request: GenerationRequest) -> str:
    return (
        request.instructions
        + "\nReturn only JSON matching this JSON schema:\n"
        + json.dumps(request.json_schema)
    )


def user_content(request: GenerationRequest) -> str:
    content = "Product requirements (data):\n" + request.requirement.model_dump_json()
    if request.repair_feedback is not None:
        content += (
            "\nRepair feedback (data):\n" + request.repair_feedback.model_dump_json()
        )
    return content


class HTTPModelAdapter(ABC):
    _url: str
    _headers: dict[str, str]

    def __init__(
        self, settings: RuntimeSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = (
            client if client is not None else httpx.AsyncClient(trust_env=False)
        )

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Implement the provider wire format; perform exactly one HTTP call."""
        ...

    async def _post(self, payload: dict[str, object]) -> dict[str, Any]:
        try:
            response = await self._client.post(
                self._url,
                headers=self._headers,
                json=payload,
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise SessionTimeoutError("LLM request timed out") from None
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 429:
                raise ProviderError(self._rate_limit_error(error.response)) from None
            raise ProviderError(
                f"LLM returned HTTP {error.response.status_code}"
            ) from None
        except httpx.HTTPError:
            raise ProviderError("LLM transport failed") from None
        try:
            body = response.json()
        except ValueError:
            raise ProviderError("LLM returned an invalid response envelope") from None
        if not isinstance(body, dict):
            raise ProviderError("LLM returned an invalid response envelope")
        return body

    def _rate_limit_error(self, response: httpx.Response) -> str:
        """Explain a 429 using only known provider error codes, never raw bodies."""
        provider = self._settings.provider
        error_body: object = None
        try:
            error_body = response.json().get("error")
        except ValueError, AttributeError:
            pass
        code = error_body.get("code") if isinstance(error_body, dict) else None
        status = error_body.get("status") if isinstance(error_body, dict) else None
        code_value = code if isinstance(code, str) else status
        if code_value == "insufficient_quota":
            reason = "API quota or billing limit is exhausted"
        elif code_value in {"rate_limit_exceeded", "RESOURCE_EXHAUSTED"}:
            reason = "request quota or rate limit was exceeded"
        else:
            reason = "rate limit or available API quota may have been reached"
        provider_name = {
            "gemini": "Gemini",
            "nvidia": "NVIDIA",
            "openai": "OpenAI",
        }[provider]
        return (
            f"{provider_name} returned HTTP 429: {reason}. Check the provider "
            "API quota and billing limits. No automatic retry was attempted."
        )

    async def aclose(self) -> None:
        """Close owned clients; injected clients remain caller-owned."""
        if self._owns_client:
            await self._client.aclose()
