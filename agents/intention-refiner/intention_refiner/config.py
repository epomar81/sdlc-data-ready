from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
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

    @model_validator(mode="after")
    def validate_selected_key(self):
        key = self.gemini_api_key if self.provider == "gemini" else self.nvidia_api_key
        if not key.strip():
            raise ValueError(f"INTENTION_REFINER_{self.provider.upper()}_API_KEY is required")
        return self

    def model_config_for_provider(self) -> ModelConfig:
        key = self.gemini_api_key if self.provider == "gemini" else self.nvidia_api_key
        return ModelConfig(api_key=key, model=self.model, timeout_seconds=self.timeout_seconds)
