import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from story_slicer.adapters.configuration.environment import EnvironmentConfiguration
from story_slicer.adapters.filesystem.local import LocalFileSystem
from story_slicer.adapters.llm.gemini import GeminiAdapter
from story_slicer.adapters.llm.http import HTTPModelAdapter
from story_slicer.adapters.llm.nvidia import NvidiaAdapter
from story_slicer.adapters.llm.selection import create_llm
from story_slicer.domain.models import RequirementDocument
from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import (
    ConfigurationError,
    InputError,
    ProviderError,
    SessionTimeoutError,
)
from story_slicer.ports.filesystem import FileReadRequest
from story_slicer.ports.llm import GenerationRequest, LLMPort, RepairFeedback
from tests.fixtures import settings_data


def environment() -> dict[str, str]:
    variables: dict[str, str] = {}
    for name, value in settings_data().items():
        if value is None:
            continue
        if name in {"provider", "model"}:
            name = "llm_" + name
        prefix = "" if name.startswith("otel_") else "STORY_SLICER_"
        variables[prefix + name.upper()] = str(value)
    return variables


def generation_request() -> GenerationRequest:
    return GenerationRequest(
        instructions="Slice into independent stories",
        requirement=RequirementDocument.model_validate(
            {"project": "SHOP", "requirements": [{"description": "Track orders"}]}
        ),
        json_schema={"type": "object"},
        repair_feedback=RepairFeedback(
            previous_response="broken", diagnostic="Expected JSON"
        ),
    )


def test_environment_configuration_loads_and_converts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("os.environ", environment())
    settings = EnvironmentConfiguration().load()
    assert settings.provider == "gemini" and settings.max_retries == 2
    assert settings.nvidia_api_key is None
    assert settings.otel_export_timeout_seconds == 5.0
    nvidia_env = environment() | {
        "STORY_SLICER_LLM_PROVIDER": "nvidia",
        "STORY_SLICER_NVIDIA_API_KEY": "nvidia-test",
        "STORY_SLICER_NVIDIA_BASE_URL": "https://integrate.api.nvidia.com/v1",
    }
    assert EnvironmentConfiguration(nvidia_env).load().provider == "nvidia"


def test_environment_configuration_fails_without_leaking_values() -> None:
    for change in [
        {"STORY_SLICER_MAX_RETRIES": "-1"},
        {"STORY_SLICER_GEMINI_API_KEY": ""},
        {"STORY_SLICER_LLM_PROVIDER": "test-credential"},
    ]:
        with pytest.raises(ConfigurationError) as caught:
            EnvironmentConfiguration(environment() | change).load()
        assert "test-credential" not in str(caught.value)
        assert caught.value.__cause__ is None
    with pytest.raises(ConfigurationError):
        EnvironmentConfiguration({}).load()


def test_configuration_requires_exported_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(f"{key}={value}" for key, value in environment().items()),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "story_slicer.adapters.configuration.environment._DOTENV_PATH",
        dotenv_path,
        raising=False,
    )
    monkeypatch.setattr("os.environ", {})
    with pytest.raises(ConfigurationError, match="STORY_SLICER_LLM_PROVIDER"):
        EnvironmentConfiguration().load()
    assert not os.environ


def test_explicit_configuration_does_not_modify_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("os.environ", {})
    assert EnvironmentConfiguration(environment()).load().model == "configured-model"
    assert not os.environ


def test_filesystem_reads_requested_yaml_path(tmp_path: Path) -> None:
    path = tmp_path / "requirements.yaml"
    content = b"project: SHOP\nrequirements:\n  - description: Track orders\n"
    path.write_bytes(content)
    filesystem = LocalFileSystem()
    assert (
        asyncio.run(
            filesystem.read(FileReadRequest(path=str(path), max_bytes=len(content)))
        )
        == content
    )


def test_filesystem_rejects_missing_and_oversized_files(tmp_path: Path) -> None:
    path = tmp_path / "requirements.yaml"
    filesystem = LocalFileSystem()
    request = FileReadRequest(path=str(path), max_bytes=3)
    with pytest.raises(InputError):
        asyncio.run(filesystem.read(request))
    path.write_bytes(b"too large")
    with pytest.raises(InputError, match="size limit"):
        asyncio.run(filesystem.read(request))


def test_gemini_request_and_normalized_usage() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path.endswith("/models/configured-model:generateContent")
        assert request.headers["x-goog-api-key"] == "test-credential"
        assert payload["generationConfig"]["responseJsonSchema"] == {"type": "object"}
        assert "Expected JSON" in json.dumps(payload)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 4,
                    "candidatesTokenCount": 6,
                    "thoughtsTokenCount": 2,
                },
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter: LLMPort = GeminiAdapter(
                RuntimeSettings.model_validate(settings_data()), client
            )
            result = await adapter.generate(generation_request())
            assert result.text == "{}"
            assert result.usage.input_tokens == 4 and result.usage.output_tokens == 8

    asyncio.run(run())


def test_gemini_rejects_provider_failure_without_leaking_body() -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="test-credential")
            )
        ) as client:
            adapter = GeminiAdapter(
                RuntimeSettings.model_validate(settings_data()), client
            )
            with pytest.raises(ProviderError) as caught:
                await adapter.generate(generation_request())
            assert "test-credential" not in str(caught.value)

    asyncio.run(run())


def test_gemini_missing_usage_and_invalid_envelope() -> None:
    async def run() -> None:
        response: dict[str, Any] = {
            "candidates": [{"content": {"parts": [{"text": "broken JSON"}]}}]
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response)
            )
        ) as client:
            adapter = GeminiAdapter(
                RuntimeSettings.model_validate(settings_data()), client
            )
            result = await adapter.generate(generation_request())
            assert result.text == "broken JSON" and result.usage.output_tokens is None
            response.clear()
            with pytest.raises(ProviderError):
                await adapter.generate(generation_request())

    asyncio.run(run())


def nvidia_settings() -> RuntimeSettings:
    return RuntimeSettings.model_validate(
        settings_data()
        | {
            "provider": "nvidia",
            "nvidia_api_key": "nvidia-test",
            "nvidia_base_url": "https://integrate.api.nvidia.com/v1",
        }
    )


def test_nvidia_request_and_normalized_usage() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer nvidia-test"
        assert payload["model"] == "configured-model"
        assert "Expected JSON" in json.dumps(payload)
        assert "JSON schema" in payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 9},
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter: LLMPort = NvidiaAdapter(nvidia_settings(), client)
            result = await adapter.generate(generation_request())
            assert result.text == "{}"
            assert result.usage.input_tokens == 3 and result.usage.output_tokens == 9

    asyncio.run(run())


def test_nvidia_timeout_is_typed_and_not_retried() -> None:
    requests: list[httpx.Request] = []

    def timeout(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("nvidia-test", request=request)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            with pytest.raises(SessionTimeoutError) as caught:
                await NvidiaAdapter(nvidia_settings(), client).generate(
                    generation_request()
                )
            assert "nvidia-test" not in str(caught.value)
            assert len(requests) == 1

    asyncio.run(run())


def test_nvidia_missing_usage_and_invalid_envelope() -> None:
    async def run() -> None:
        response: dict[str, Any] = {"choices": [{"message": {"content": "{}"}}]}
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response)
            )
        ) as client:
            adapter = NvidiaAdapter(nvidia_settings(), client)
            assert (
                await adapter.generate(generation_request())
            ).usage.input_tokens is None
            response.clear()
            with pytest.raises(ProviderError):
                await adapter.generate(generation_request())

    asyncio.run(run())


def test_provider_selection_and_owned_client_cleanup() -> None:
    async def run() -> None:
        gemini = create_llm(RuntimeSettings.model_validate(settings_data()))
        nvidia = create_llm(nvidia_settings())
        assert isinstance(gemini, GeminiAdapter) and isinstance(nvidia, NvidiaAdapter)
        await gemini.aclose()
        await nvidia.aclose()

    asyncio.run(run())


def test_gemini_rejects_ai_studio_web_page_as_api_endpoint() -> None:
    settings = RuntimeSettings.model_validate(
        settings_data()
        | {"gemini_base_url": "https://aistudio.google.com/api-keys?project=private-id"}
    )
    with pytest.raises(ConfigurationError) as caught:
        GeminiAdapter(settings)
    assert "https://generativelanguage.googleapis.com/v1beta" in str(caught.value)
    assert "private-id" not in str(caught.value)


def test_empty_inactive_provider_credentials_are_ignored() -> None:
    variables = environment() | {
        "STORY_SLICER_OPENAI_API_KEY": "",
        "STORY_SLICER_OPENAI_BASE_URL": "",
        "STORY_SLICER_NVIDIA_API_KEY": "",
        "STORY_SLICER_NVIDIA_BASE_URL": "",
    }
    settings = EnvironmentConfiguration(variables).load()
    assert settings.provider == "gemini"
    assert settings.openai_api_key is None and settings.openai_base_url is None
    assert settings.nvidia_api_key is None and settings.nvidia_base_url is None


def test_missing_selected_provider_credential_is_reported_clearly() -> None:
    variables = environment() | {"STORY_SLICER_GEMINI_API_KEY": ""}
    with pytest.raises(ConfigurationError, match="STORY_SLICER_GEMINI_API_KEY"):
        EnvironmentConfiguration(variables).load()


def test_missing_gemini_key_error_gives_provider_specific_fix() -> None:
    variables = environment() | {"STORY_SLICER_GEMINI_API_KEY": ""}
    with pytest.raises(ConfigurationError) as caught:
        EnvironmentConfiguration(variables).load()
    message = str(caught.value)
    assert "Gemini is selected" in message
    assert "STORY_SLICER_GEMINI_API_KEY" in message
    assert "No LLM API keys are configured" in message


def test_missing_selected_key_points_to_configured_alternate_provider() -> None:
    variables = environment() | {
        "STORY_SLICER_GEMINI_API_KEY": "",
        "STORY_SLICER_OPENAI_API_KEY": "openai-test-key",
        "STORY_SLICER_OPENAI_BASE_URL": "https://api.openai.com/v1",
    }
    with pytest.raises(ConfigurationError) as caught:
        EnvironmentConfiguration(variables).load()
    message = str(caught.value)
    assert "Gemini is selected" in message
    assert "OpenAI is configured" in message
    assert "STORY_SLICER_LLM_PROVIDER=openai" in message


@pytest.mark.parametrize(
    "case",
    [
        (
            "gemini",
            {"error": {"status": "RESOURCE_EXHAUSTED", "message": "private-project"}},
            "request quota or rate limit was exceeded",
        ),
        (
            "openai",
            {"error": {"code": "insufficient_quota", "message": "private-project"}},
            "API quota or billing limit is exhausted",
        ),
    ],
)
def test_rate_limit_error_explains_quota_without_exposing_response_body(
    case: tuple[str, dict[str, object], str],
) -> None:
    provider, error_body, expected = case
    settings = settings_data()
    adapter_type: type[HTTPModelAdapter]
    if provider == "openai":
        settings |= {
            "provider": "openai",
            "gemini_api_key": None,
            "gemini_base_url": None,
            "openai_api_key": "openai-test-key",
            "openai_base_url": "https://api.openai.com/v1",
        }
        from story_slicer.adapters.llm.openai import OpenAIAdapter

        adapter_type = OpenAIAdapter
    else:
        adapter_type = GeminiAdapter
    with pytest.raises(ProviderError) as caught:

        async def run() -> None:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(429, json=error_body)
                )
            ) as client:
                await adapter_type(
                    RuntimeSettings.model_validate(settings), client
                ).generate(generation_request())

        asyncio.run(run())
    assert expected in str(caught.value)
    assert "HTTP 429" in str(caught.value)
    assert "private-project" not in str(caught.value)
