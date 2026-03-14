"""Abstract broker interface for message broker implementations.

Defines the protocol that both Redis-backed and in-memory brokers implement,
enabling dependency injection and infrastructure-free testing.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class MessageBrokerProtocol(Protocol):
    """Protocol for message broker implementations.

    Both ``MessageBroker`` (Redis Streams) and ``InMemoryMessageBroker``
    satisfy this interface, allowing agent runners and communication hubs
    to be wired to either backend.
    """

    async def publish(self, channel: str, message: dict[str, Any]) -> str:
        """Publish a message to *channel*.

        Returns an implementation-defined message ID string.
        """
        ...

    async def subscribe(
        self,
        channel: str,
        callback: Callable[[dict[str, Any]], Any],
        consumer_group: str | None = None,
        consumer_name: str | None = None,
    ) -> None:
        """Subscribe to *channel*, invoking *callback* for each message.

        This is expected to block (loop internally) until cancelled.
        """
        ...

    async def replay(
        self,
        channel: str,
        start_id: str = "0",
        count: int = 100,
    ) -> list[dict[str, Any]]:
        """Replay up to *count* historical messages from *channel*."""
        ...
