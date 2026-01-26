"""OpenAI implementation of the LLM provider interface."""
from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from ..base import LLMProvider, LLMResult

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """Adapter for OpenAI's Chat Completions API."""

    name = "openai"

    def __init__(self, api_key: str, default_model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.default_model = default_model

    async def chat(
        self,
        messages: list[dict[str, str]],
        config: dict[str, Any] | None = None,
    ) -> LLMResult:
        config = config or {}
        model = config.get("model") or self.default_model
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 500)
        tools = config.get("tools")  # OpenAI function calling format

        logger.debug(
            "OpenAI chat request model=%s temperature=%s max_tokens=%s tools=%s",
            model,
            temperature,
            max_tokens,
            len(tools) if tools else 0,
        )

        # Build API call parameters
        api_params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": config.get("top_p", 1.0),
            "frequency_penalty": config.get("frequency_penalty", 0.0),
            "presence_penalty": config.get("presence_penalty", 0.0),
        }

        # Add tools if provided
        if tools:
            api_params["tools"] = tools
            # Optional: force tool use with tool_choice
            if config.get("tool_choice"):
                api_params["tool_choice"] = config["tool_choice"]

        response = await self.client.chat.completions.create(**api_params)

        choice = response.choices[0]
        content = choice.message.content or ""

        usage_dict = response.usage.model_dump() if response.usage else None

        # Extract tool calls if present
        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]

        metadata = {
            "finish_reason": choice.finish_reason,
        }

        return LLMResult(
            provider=self.name,
            model=model,
            content=content,
            finish_reason=choice.finish_reason,
            usage=usage_dict,
            raw_response_id=response.id,
            metadata=metadata,
            tool_calls=tool_calls,
        )
