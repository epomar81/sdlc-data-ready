from google import genai
from google.genai import types
from openai import OpenAI

from intention_refiner.application.ports import ModelResponse
from intention_refiner.config import ModelConfig, Settings


class ModelRequestError(RuntimeError):
    """A configured model did not return usable text."""


class GeminiAdapter:
    def __init__(self, config: ModelConfig):
        self.config = config

    def generate(self, prompt: str) -> ModelResponse:
        try:
            client = genai.Client(
                api_key=self.config.api_key,
                http_options=types.HttpOptions(timeout=int(self.config.timeout_seconds * 1000)),
            )
            chat = client.chats.create(
                model=self.config.model,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            response = chat.send_message(prompt)
            if not response.text:
                raise ModelRequestError("Gemini returned an empty response")
            usage = response.usage_metadata
            return ModelResponse(
                text=response.text,
                prompt_tokens=usage.prompt_token_count,
                completion_tokens=usage.candidates_token_count,
                total_tokens=usage.total_token_count,
            )
        except ModelRequestError:
            raise
        except Exception as exc:
            raise ModelRequestError(f"Gemini request failed: {exc}") from exc


class NvidiaAdapter:
    def __init__(self, config: ModelConfig):
        self.config = config

    def generate(self, prompt: str) -> ModelResponse:
        try:
            client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=self.config.api_key,
                timeout=self.config.timeout_seconds,
                max_retries=0,
            )
            response = client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise ModelRequestError("NVIDIA returned an empty response")
            usage = response.usage
            return ModelResponse(
                text=content,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )
        except ModelRequestError:
            raise
        except Exception as exc:
            raise ModelRequestError(f"NVIDIA request failed: {exc}") from exc


def build_model(settings: Settings) -> GeminiAdapter | NvidiaAdapter:
    config = settings.model_config_for_provider()
    if settings.provider == "gemini":
        return GeminiAdapter(config)
    return NvidiaAdapter(config)
