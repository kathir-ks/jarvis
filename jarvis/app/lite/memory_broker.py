"""In-memory message broker — zero-infrastructure drop-in for MessageBroker.

Uses ``asyncio.Queue`` per channel with an in-memory history list so that
``replay()`` works.  Designed for single-process demos where multiple
``LiteAgentRunner`` instances share the same broker object.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable

logger = logging.getLogger(__name__)


class InMemoryMessageBroker:
    """Drop-in replacement for the Redis-backed ``MessageBroker``.

    Satisfies ``MessageBrokerProtocol`` using pure asyncio primitives.
    """

    def __init__(self, max_history_per_channel: int = 1000):
        self._max_history = max_history_per_channel

        # channel -> list of (msg_id, message) tuples
        self._history: dict[str, list[tuple[str, dict[str, Any]]]] = {}

        # channel -> list of subscriber callbacks
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}

    # ------------------------------------------------------------------
    # publish
    # ------------------------------------------------------------------

    async def publish(self, channel: str, message: dict[str, Any]) -> str:
        """Store message in history and notify all subscribers immediately."""
        msg_id = f"{channel}-{uuid.uuid4().hex[:12]}"

        # Append to history
        if channel not in self._history:
            self._history[channel] = []
        self._history[channel].append((msg_id, message))

        # Trim history
        if len(self._history[channel]) > self._max_history:
            self._history[channel] = self._history[channel][-self._max_history:]

        # Fan-out to all current subscribers
        for cb in list(self._subscribers.get(channel, [])):
            try:
                result = cb(message)
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except Exception as exc:
                logger.error("Subscriber callback error on %s: %s", channel, exc)

        logger.debug("Published to %s (id=%s, subscribers=%d)",
                      channel, msg_id, len(self._subscribers.get(channel, [])))
        return msg_id

    # ------------------------------------------------------------------
    # subscribe
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        channel: str,
        callback: Callable[[dict[str, Any]], Any],
        consumer_group: str | None = None,
        consumer_name: str | None = None,
    ) -> None:
        """Register *callback* for *channel*.

        Unlike the Redis version this does **not** block in a loop — it simply
        registers the callback.  Messages arriving via ``publish()`` will
        invoke the callback inline (in the publisher's coroutine context).

        ``consumer_group`` and ``consumer_name`` are accepted for interface
        compatibility but ignored (no consumer-group semantics needed in a
        single-process in-memory broker).
        """
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(callback)
        logger.debug("Subscribed to %s (total=%d)", channel, len(self._subscribers[channel]))

    # ------------------------------------------------------------------
    # unsubscribe (extra convenience — not in the protocol)
    # ------------------------------------------------------------------

    def unsubscribe(self, channel: str, callback: Callable) -> bool:
        """Remove a previously registered callback. Returns True if found."""
        subs = self._subscribers.get(channel, [])
        try:
            subs.remove(callback)
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # replay
    # ------------------------------------------------------------------

    async def replay(
        self,
        channel: str,
        start_id: str = "0",
        count: int = 100,
    ) -> list[dict[str, Any]]:
        """Return up to *count* messages from the channel's history.

        ``start_id`` filtering is simplified: ``"0"`` returns from the
        beginning; any other value skips messages whose ID is ≤ start_id.
        """
        history = self._history.get(channel, [])

        if start_id and start_id != "0":
            # Find the start position
            start_idx = 0
            for i, (mid, _) in enumerate(history):
                if mid == start_id:
                    start_idx = i + 1
                    break
            history = history[start_idx:]

        return [msg for _, msg in history[:count]]
