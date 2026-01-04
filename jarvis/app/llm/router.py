"""LLM gateway stub."""
from typing import Any


class LLMRouter:
    """Routes LLM calls to providers."""

    async def call(self, prompt: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call LLM with prompt."""
        # Placeholder: route to OpenAI/Anthropic/Gemini
        return {"response": "LLM response placeholder", "tokens": 0}
