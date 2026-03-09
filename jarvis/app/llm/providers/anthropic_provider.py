"""Anthropic Claude implementation of the LLM provider interface."""
from __future__ import annotations

import logging
from typing import Any

from anthropic import AsyncAnthropic

from ..base import LLMProvider, LLMResult

logger = logging.getLogger(__name__)

# Default max tokens for Anthropic models (they require an explicit value)
_DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(LLMProvider):
    """Adapter for Anthropic's Messages API."""

    name = "anthropic"

    def __init__(self, api_key: str, default_model: str) -> None:
        self.client = AsyncAnthropic(api_key=api_key)
        self.default_model = default_model

    async def chat(
        self,
        messages: list[dict[str, str]],
        config: dict[str, Any] | None = None,
    ) -> LLMResult:
        config = config or {}
        model = config.get("model") or self.default_model
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens") or _DEFAULT_MAX_TOKENS
        tools = config.get("tools")

        logger.debug(
            "Anthropic chat request model=%s temperature=%s max_tokens=%s tools=%s",
            model,
            temperature,
            max_tokens,
            len(tools) if tools else 0,
        )

        # Separate system message from conversation messages
        system_text, claude_messages = self._convert_messages(messages)

        # Build API call parameters
        api_params: dict[str, Any] = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if system_text:
            api_params["system"] = system_text

        if tools:
            api_params["tools"] = self._convert_tools(tools)

        try:
            response = await self.client.messages.create(**api_params)
        except Exception as e:
            logger.error("Anthropic API call failed: %s", e, exc_info=True)
            raise

        # Extract text content and tool use blocks
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": block.input,
                    },
                })

        content = "\n".join(content_parts)

        usage_dict = None
        if response.usage:
            usage_dict = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }

        metadata = {
            "finish_reason": response.stop_reason,
            "model": response.model,
        }

        return LLMResult(
            provider=self.name,
            model=response.model,
            content=content,
            finish_reason=response.stop_reason,
            usage=usage_dict,
            raw_response_id=response.id,
            metadata=metadata,
            tool_calls=tool_calls if tool_calls else None,
        )

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, str]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Convert OpenAI-style messages to Anthropic format.

        Returns:
            A tuple of (system_text, claude_messages).
        """
        system_parts: list[str] = []
        claude_messages: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_parts.append(content)
                continue

            if role == "tool":
                # Tool results are sent as user messages with tool_result blocks
                claude_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": content,
                        }
                    ],
                })
                continue

            # Map assistant/user directly
            claude_role = "assistant" if role == "assistant" else "user"
            claude_messages.append({
                "role": claude_role,
                "content": content,
            })

        system_text = "\n\n".join(system_parts) if system_parts else ""
        return system_text, claude_messages

    # ------------------------------------------------------------------
    # Tool conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools(openai_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI-format tool definitions to Anthropic format.

        OpenAI format::

            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": { JSON Schema }
                }
            }

        Anthropic format::

            {
                "name": "...",
                "description": "...",
                "input_schema": { JSON Schema }
            }
        """
        anthropic_tools: list[dict[str, Any]] = []

        for tool in openai_tools:
            if tool.get("type") != "function":
                continue
            func = tool.get("function", {})
            anthropic_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })

        return anthropic_tools
