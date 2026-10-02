import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from story_slicer.adapters.configuration.environment import EnvironmentConfiguration
from story_slicer.adapters.llm.openai import OpenAIAdapter
from story_slicer.adapters.llm.selection import create_llm
from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import (
    ConfigurationError,
    ProviderError,
    SessionTimeoutError,
)
from tests.fixtures import settings_data
from tests.test_adapters import environment, generation_request


def openai_settings() -> RuntimeSettings:
    return RuntimeSettings.model_validate(
        settings_data()
        | {
            "provider": "openai",
            "model": "configured-openai-model",
            "gemini_api_key": None,
            "gemini_base_url": None,
            "openai_api_key": "openai-test-key",
            "openai_base_url": "https://api.openai.com/v1",
        }
    )


def response_body() -> dict[str, Any]:
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": "{}"}]},
        ],
        "usage": {"input_tokens": 4, "output_tokens": 6},
    }


def test_openai_request_response_and_selection() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer openai-test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "configured-openai-model"
        assert payload["store"] is False
        assert payload["text"]["format"] == {"type": "json_object"}
        assert "JSON schema" in payload["instructions"]
        assert "Expected JSON" in payload["input"]
        assert "Track orders" in payload["input"]
        return httpx.Response(200, json=response_body())

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter = create_llm(openai_settings(), client)
            assert isinstance(adapter, OpenAIAdapter)
            result = await adapter.generate(generation_request())
            assert result.text == "{}"
            assert result.usage.input_tokens == 4 and result.usage.output_tokens == 6
            await adapter.aclose()
            assert not client.is_closed
        owned = create_llm(openai_settings())
        await owned.aclose()

    asyncio.run(run())


def test_openai_environment_loads_without_other_provider_credentials() -> None:
    variables = environment() | {
        "STORY_SLICER_LLM_PROVIDER": "openai",
        "STORY_SLICER_OPENAI_API_KEY": "openai-test-key",
        "STORY_SLICER_OPENAI_BASE_URL": "https://api.openai.com/v1",
    }
    variables.pop("STORY_SLICER_GEMINI_API_KEY")
    variables.pop("STORY_SLICER_GEMINI_BASE_URL")
    settings = EnvironmentConfiguration(variables).load()
    assert settings.provider == "openai" and settings.gemini_api_key is None
    for field in ["STORY_SLICER_OPENAI_API_KEY", "STORY_SLICER_OPENAI_BASE_URL"]:
        with pytest.raises(ConfigurationError):
            EnvironmentConfiguration(
                {key: value for key, value in variables.items() if key != field}
            ).load()


@pytest.mark.parametrize("change", [{"openai_api_key": " "}, {"openai_base_url": None}])
def test_openai_requires_credentials_and_endpoint(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings.model_validate(openai_settings().model_dump() | change)
    with pytest.raises(ConfigurationError):
        OpenAIAdapter(RuntimeSettings.model_validate(settings_data()))


@pytest.mark.parametrize(
    "body",
    [
        {"status": "incomplete", "output": []},
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "refusal", "refusal": "private-data"}],
                }
            ],
        },
        {"status": "completed", "output": "wrong-type"},
        {"status": "completed", "output": []},
        response_body() | {"usage": {"input_tokens": -1}},
    ],
)
def test_openai_rejects_invalid_or_refused_response(body: dict[str, Any]) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=body)
            )
        ) as client:
            with pytest.raises(ProviderError) as caught:
                await OpenAIAdapter(openai_settings(), client).generate(
                    generation_request()
                )
            assert "private-data" not in str(caught.value)

    asyncio.run(run())


def test_openai_usage_can_be_unknown() -> None:
    body = response_body()
    body.pop("usage")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=body)
            )
        ) as client:
            result = await OpenAIAdapter(openai_settings(), client).generate(
                generation_request()
            )
            assert (
                result.usage.input_tokens is None and result.usage.output_tokens is None
            )

    asyncio.run(run())


@pytest.mark.parametrize("timeout", [False, True])
def test_openai_http_failures_do_not_leak_or_retry(timeout: bool) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if timeout:
            raise httpx.ReadTimeout("openai-test-key", request=request)
        return httpx.Response(401, text="openai-test-key")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(
                SessionTimeoutError if timeout else ProviderError
            ) as caught:
                await OpenAIAdapter(openai_settings(), client).generate(
                    generation_request()
                )
            assert "openai-test-key" not in str(caught.value)

    asyncio.run(run())
    assert calls == 1
