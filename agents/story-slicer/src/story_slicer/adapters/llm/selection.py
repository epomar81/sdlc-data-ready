"""Select a provider at composition time, outside the core."""

import httpx

from story_slicer.adapters.llm.gemini import GeminiAdapter
from story_slicer.adapters.llm.http import HTTPModelAdapter
from story_slicer.adapters.llm.nvidia import NvidiaAdapter
from story_slicer.adapters.llm.openai import OpenAIAdapter
from story_slicer.ports.configuration import RuntimeSettings


def create_llm(
    settings: RuntimeSettings, client: httpx.AsyncClient | None = None
) -> HTTPModelAdapter:
    if settings.provider == "gemini":
        return GeminiAdapter(settings, client)
    if settings.provider == "openai":
        return OpenAIAdapter(settings, client)
    return NvidiaAdapter(settings, client)
