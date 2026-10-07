from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelConfig(BaseModel):
    api_key: str = Field(min_length=1, repr=False)
    model: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INTENTION_REFINER_", extra="ignore")

    provider: Literal["gemini", "nvidia"]
    model: str = Field(min_length=1)
    gemini_api_key: str = Field(default="", repr=False)
    nvidia_api_key: str = Field(default="", repr=False)
    timeout_seconds: float = Field(default=120, gt=0)
    output_path: Path = Path("output_requirements.yaml")
    telemetry_enabled: bool = False
    metrics_exporter: Literal["console", "otlp"] = "console"
    github_token: SecretStr = SecretStr("")
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: SecretStr = SecretStr("")
    integration_timeout_seconds: float = Field(default=30, gt=0)

    def integration_config(
        self, provider: Literal["github", "jira"]
    ) -> "IntegrationConfig":
        return IntegrationConfig(
            provider=provider,
            github_token=self.github_token,
            jira_base_url=self.jira_base_url,
            jira_email=self.jira_email,
            jira_api_token=self.jira_api_token,
            timeout_seconds=self.integration_timeout_seconds,
        )

    @model_validator(mode="after")
    def validate_selected_key(self):
        key = self.gemini_api_key if self.provider == "gemini" else self.nvidia_api_key
        if not key.strip():
            raise ValueError(
                f"INTENTION_REFINER_{self.provider.upper()}_API_KEY is required"
            )
        return self

    def model_config_for_provider(self) -> ModelConfig:
        key = self.gemini_api_key if self.provider == "gemini" else self.nvidia_api_key
        return ModelConfig(
            api_key=key, model=self.model, timeout_seconds=self.timeout_seconds
        )


class IntegrationConfig(BaseModel):
    provider: Literal["github", "jira"]
    github_token: SecretStr = SecretStr("")
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: SecretStr = SecretStr("")
    timeout_seconds: float = Field(default=30, gt=0)

    @model_validator(mode="after")
    def validate_provider(self):
        if self.provider == "github":
            if not self.github_token.get_secret_value().strip():
                raise ValueError("INTENTION_REFINER_GITHUB_TOKEN is required")
        else:
            parsed = urlsplit(self.jira_base_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or not parsed.hostname.endswith(".atlassian.net")
                or parsed.username
                or parsed.password
                or parsed.port
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "JIRA_BASE_URL must be an HTTPS Jira Cloud site origin"
                )
            self.jira_base_url = self.jira_base_url.rstrip("/")
            if (
                not self.jira_email.strip()
                or not self.jira_api_token.get_secret_value().strip()
            ):
                raise ValueError("JIRA_EMAIL and JIRA_API_TOKEN are required")
        return self


class SourceLabels(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    clarification: str = Field(default="question", min_length=1)
    ai_review: str = Field(default="help wanted", min_length=1)


class ProviderLabels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defaults: dict[Literal["clarification", "ai_review"], str] = Field(
        default_factory=dict
    )
    projects: dict[str, dict[Literal["clarification", "ai_review"], str]] = Field(
        default_factory=dict
    )


class LabelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    github: ProviderLabels = Field(default_factory=ProviderLabels)
    jira: ProviderLabels = Field(default_factory=ProviderLabels)

    @classmethod
    def load(cls, path: Path | None):
        if path is None:
            return cls()
        import yaml

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return cls.model_validate(data)
        except (ValueError, yaml.YAMLError):
            raise ValueError("Invalid integration label configuration") from None

    def for_source(self, source) -> SourceLabels:
        provider = getattr(self, source.provider)
        project = (
            source.reference.split("#")[0]
            if source.provider == "github"
            else source.reference.rsplit("-", 1)[0]
        )
        data = {
            "clarification": "question",
            "ai_review": "help wanted" if source.provider == "github" else "ai-review",
        }
        data.update(provider.defaults)
        data.update(provider.projects.get(project, {}))
        labels = SourceLabels.model_validate(data)
        for label in (labels.clarification, labels.ai_review):
            if (
                not label.strip()
                or len(label) > (50 if source.provider == "github" else 255)
                or any(ord(char) < 32 for char in label)
                or (source.provider == "jira" and any(char.isspace() for char in label))
            ):
                raise ValueError("Invalid provider label name")
        return labels
