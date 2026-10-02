"""Runtime settings contract; environment loading belongs to an adapter."""

from typing import Literal, Protocol, Self

from pydantic import HttpUrl, SecretStr, field_validator, model_validator

from story_slicer.domain.models import NonBlank
from story_slicer.ports.contracts import (
    ContractModel,
    ErrorRate,
    NonNegativeInteger,
    PositiveInteger,
    PositiveSeconds,
    Provider,
)


class RuntimeSettings(ContractModel):
    """All settings are explicit; nullable inactive-provider settings are required."""

    provider: Provider
    model: NonBlank
    gemini_api_key: SecretStr | None
    gemini_base_url: HttpUrl | None
    nvidia_api_key: SecretStr | None
    nvidia_base_url: HttpUrl | None
    openai_api_key: SecretStr | None = None
    openai_base_url: HttpUrl | None = None
    max_retries: NonNegativeInteger
    request_timeout_seconds: PositiveSeconds
    session_timeout_seconds: PositiveSeconds
    max_input_bytes: PositiveInteger
    schema_error_rate_threshold: ErrorRate
    schema_error_min_attempts: PositiveInteger
    otel_service_name: NonBlank
    otel_exporter_otlp_endpoint: HttpUrl
    otel_export_interval_seconds: PositiveSeconds
    otel_export_timeout_seconds: PositiveSeconds
    otel_export_mode: Literal["disabled", "otlp"] = "disabled"

    @field_validator("gemini_api_key", "nvidia_api_key", "openai_api_key")
    @classmethod
    def validate_nonblank_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("Credentials cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_selected_provider(self) -> Self:
        if self.provider == "gemini" and (
            self.gemini_api_key is None or self.gemini_base_url is None
        ):
            raise ValueError("Gemini requires its API key and endpoint")
        if self.provider == "nvidia" and (
            self.nvidia_api_key is None or self.nvidia_base_url is None
        ):
            raise ValueError("NVIDIA requires its API key and endpoint")
        if self.provider == "openai" and (
            self.openai_api_key is None or self.openai_base_url is None
        ):
            raise ValueError("OpenAI requires its API key and endpoint")
        return self


class ConfigurationPort(Protocol):
    def load(self) -> RuntimeSettings:
        """Return validated settings or raise ConfigurationError."""
        ...
