"""Shared interfaces and data structures for LLM providers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class LLMResult:
    """Normalized response returned by every LLM provider."""

    provider: str
    model: str
    content: str
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    raw_response_id: str | None = None
    metadata: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None  # Tool calls made by the LLM


@runtime_checkable
class LLMProvider(Protocol):
    """Common interface each LLM provider implementation must satisfy."""

    name: str

    async def chat(
        self,
        messages: list[dict[str, str]],
        config: dict[str, Any] | None = None,
    ) -> LLMResult:
        """Execute chat completion request."""
        ...
