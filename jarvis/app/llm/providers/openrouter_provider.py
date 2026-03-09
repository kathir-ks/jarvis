"""OpenRouter provider — OpenAI-compatible API with free model access."""
from __future__ import annotations

from openai import AsyncOpenAI

from .openai_provider import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter uses the OpenAI-compatible API with a different base URL.

    Sign up at https://openrouter.ai/ for a free API key.
    Free models use the `:free` suffix, e.g. ``meta-llama/llama-3.1-8b-instruct:free``.
    """

    name = "openrouter"

    def __init__(self, api_key: str, default_model: str) -> None:
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        self.default_model = default_model
