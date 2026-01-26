"""LLM gateway that routes through provider implementations."""
from __future__ import annotations

import logging
from typing import Any

from ..core.settings import get_settings, Settings
from .base import LLMProvider, LLMResult
from .providers import OpenAIProvider, GeminiProvider

logger = logging.getLogger(__name__)


class LLMRouter:
    """Routes LLM calls to whichever provider is configured."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.providers: dict[str, LLMProvider] = self._load_providers()
        self.default_provider = self.settings.default_llm_provider

    async def call(
        self,
        messages: list[dict[str, str]],
        config: dict[str, Any] | None = None,
    ) -> LLMResult:
        """Call an LLM provider with chat-style messages."""
        config = config or {}
        provider_name = config.get("provider") or self.default_provider

        provider = self.providers.get(provider_name)
        if not provider:
            raise ValueError(f"LLM provider '{provider_name}' is not configured.")

        logger.debug("Routing LLM request to provider=%s", provider_name)
        return await provider.chat(messages, config)

    def _load_providers(self) -> dict[str, LLMProvider]:
        """Instantiate available providers based on configuration."""
        providers: dict[str, LLMProvider] = {}

        if self.settings.openai_api_key:
            providers["openai"] = OpenAIProvider(
                api_key=self.settings.openai_api_key,
                default_model=self.settings.default_llm_model,
            )
            logger.info("OpenAI provider configured with model=%s", self.settings.default_llm_model)
        else:
            logger.warning("OpenAI provider not configured (missing API key).")

        if self.settings.gemini_api_key:
            providers["gemini"] = GeminiProvider(
                api_key=self.settings.gemini_api_key,
                default_model=self.settings.default_gemini_model,
            )
            logger.info("Gemini provider configured with model=%s", self.settings.default_gemini_model)
        else:
            logger.warning("Gemini provider not configured (missing API key).")

        if not providers:
            logger.error("No LLM providers configured! Please set JARVIS_OPENAI_API_KEY or JARVIS_GEMINI_API_KEY")

        return providers
