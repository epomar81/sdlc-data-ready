"""Runtime configuration from exported environment variables."""

import os
from collections.abc import Mapping

from pydantic import ValidationError

from story_slicer.ports.configuration import RuntimeSettings
from story_slicer.ports.errors import ConfigurationError

ENVIRONMENT_FIELDS = {
    "provider": "STORY_SLICER_LLM_PROVIDER",
    "model": "STORY_SLICER_LLM_MODEL",
    "gemini_api_key": "STORY_SLICER_GEMINI_API_KEY",
    "gemini_base_url": "STORY_SLICER_GEMINI_BASE_URL",
    "nvidia_api_key": "STORY_SLICER_NVIDIA_API_KEY",
    "nvidia_base_url": "STORY_SLICER_NVIDIA_BASE_URL",
    "openai_api_key": "STORY_SLICER_OPENAI_API_KEY",
    "openai_base_url": "STORY_SLICER_OPENAI_BASE_URL",
    "max_retries": "STORY_SLICER_MAX_RETRIES",
    "request_timeout_seconds": "STORY_SLICER_REQUEST_TIMEOUT_SECONDS",
    "session_timeout_seconds": "STORY_SLICER_SESSION_TIMEOUT_SECONDS",
    "max_input_bytes": "STORY_SLICER_MAX_INPUT_BYTES",
    "schema_error_rate_threshold": "STORY_SLICER_SCHEMA_ERROR_RATE_THRESHOLD",
    "schema_error_min_attempts": "STORY_SLICER_SCHEMA_ERROR_MIN_ATTEMPTS",
    "otel_service_name": "OTEL_SERVICE_NAME",
    "otel_exporter_otlp_endpoint": "OTEL_EXPORTER_OTLP_ENDPOINT",
    "otel_export_interval_seconds": "OTEL_EXPORT_INTERVAL_SECONDS",
    "otel_export_timeout_seconds": "OTEL_EXPORT_TIMEOUT_SECONDS",
}
_NULLABLE_FIELDS = {
    "gemini_api_key",
    "gemini_base_url",
    "nvidia_api_key",
    "nvidia_base_url",
    "openai_api_key",
    "openai_base_url",
}
_PROVIDER_SETTINGS = {
    "gemini": ("gemini_api_key", "gemini_base_url"),
    "nvidia": ("nvidia_api_key", "nvidia_base_url"),
    "openai": ("openai_api_key", "openai_base_url"),
}
_PROVIDER_NAMES = {"gemini": "Gemini", "nvidia": "NVIDIA", "openai": "OpenAI"}
_INTEGER_FIELDS = {"max_retries", "max_input_bytes", "schema_error_min_attempts"}
_FLOAT_FIELDS = {
    "request_timeout_seconds",
    "session_timeout_seconds",
    "schema_error_rate_threshold",
    "otel_export_interval_seconds",
    "otel_export_timeout_seconds",
}


class EnvironmentConfiguration:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = environment

    def load(self) -> RuntimeSettings:
        environment = os.environ if self._environment is None else self._environment
        values: dict[str, object] = {
            "otel_export_mode": environment.get("OTEL_EXPORT_MODE", "disabled")
        }
        for field, variable in ENVIRONMENT_FIELDS.items():
            value = environment.get(variable)
            if value is None:
                if field not in _NULLABLE_FIELDS:
                    raise ConfigurationError(
                        f"Missing environment variable: {variable}"
                    )
                values[field] = None
                continue
            if field in _NULLABLE_FIELDS and not value.strip():
                values[field] = None
                continue
            try:
                if field in _INTEGER_FIELDS:
                    values[field] = int(value)
                elif field in _FLOAT_FIELDS:
                    values[field] = float(value)
                else:
                    values[field] = value
            except ValueError:
                raise ConfigurationError(
                    f"Invalid environment variable: {variable}"
                ) from None
        provider = values.get("provider")
        if isinstance(provider, str) and provider in _PROVIDER_SETTINGS:
            missing = [
                ENVIRONMENT_FIELDS[field]
                for field in _PROVIDER_SETTINGS[provider]
                if values.get(field) is None
            ]
            if missing:
                key_field, _ = _PROVIDER_SETTINGS[provider]
                if values.get(key_field) is None:
                    available = [
                        name
                        for name, (
                            candidate_key,
                            candidate_url,
                        ) in _PROVIDER_SETTINGS.items()
                        if name != provider
                        and values.get(candidate_key) is not None
                        and values.get(candidate_url) is not None
                    ]
                    provider_name = _PROVIDER_NAMES[provider]
                    if available:
                        alternatives = ", ".join(
                            _PROVIDER_NAMES[name] for name in available
                        )
                        selection = " or ".join(
                            f"STORY_SLICER_LLM_PROVIDER={name}" for name in available
                        )
                        raise ConfigurationError(
                            f"{provider_name} is selected, but its API key is missing. "
                            f"Set {ENVIRONMENT_FIELDS[key_field]} in .envrc. "
                            f"{alternatives} is configured; switch with "
                            f"{selection}."
                        )
                    raise ConfigurationError(
                        "No LLM API keys are configured. "
                        f"{provider_name} is selected; add its key to .envrc as "
                        f"{ENVIRONMENT_FIELDS[key_field]}."
                    )
                raise ConfigurationError(
                    "Missing settings for selected provider: " + ", ".join(missing)
                )
        try:
            return RuntimeSettings.model_validate(values)
        except ValidationError as error:
            fields = sorted(
                {
                    str(item["loc"][0])
                    if item["loc"]
                    else "selected provider credentials/endpoint"
                    for item in error.errors(include_input=False, include_context=False)
                }
            )
            raise ConfigurationError("Invalid settings: " + ", ".join(fields)) from None
