"""Redis Streams messaging client with durable message persistence.

Replaces fire-and-forget Pub/Sub with Redis Streams for:
- Message durability (messages survive subscriber downtime)
- Consumer groups (at-least-once delivery)
- Message acknowledgment
- Dead-letter handling for failed messages
- Replay capability from any point in the stream
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from ..db.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Maximum stream length before trimming old entries (per channel)
DEFAULT_MAX_STREAM_LENGTH = 10_000

# How long to block waiting for new messages (milliseconds)
STREAM_BLOCK_MS = 1000

# Maximum delivery attempts before moving to dead-letter
MAX_DELIVERY_ATTEMPTS = 5


class MessageBroker:
    """Redis Streams wrapper for durable agent messaging.

    Uses Redis Streams instead of Pub/Sub to guarantee message persistence.
    Messages are retained in the stream even when no subscriber is active,
    and consumers track their position via consumer groups.
    """

    def __init__(self, max_stream_length: int = DEFAULT_MAX_STREAM_LENGTH):
        self.client = get_redis_client()
        self.max_stream_length = max_stream_length

    async def publish(self, channel: str, message: dict[str, Any]) -> str:
        """Publish message to a stream (durable).

        Args:
            channel: Stream name (e.g. "agent:{id}:inbox").
            message: Message payload dict.

        Returns:
            The stream entry ID assigned by Redis.
        """
        payload = json.dumps(message)
        entry_id = await self.client.xadd(
            channel,
            {"payload": payload},
            maxlen=self.max_stream_length,
            approximate=True,
        )
        logger.info("Published to stream %s (id=%s)", channel, entry_id)
        return entry_id

    async def subscribe(
        self,
        channel: str,
        callback: Callable[[dict[str, Any]], Any],
        consumer_group: str | None = None,
        consumer_name: str | None = None,
    ) -> None:
        """Subscribe to a stream and invoke callback for each new message.

        Supports two modes:
        1. Simple mode (no consumer_group): reads from latest, Pub/Sub-like behaviour.
        2. Consumer group mode: at-least-once delivery with acknowledgment.

        Args:
            channel: Stream name.
            callback: Async callable invoked with each deserialized message.
            consumer_group: Optional consumer group name for at-least-once delivery.
            consumer_name: Consumer name within the group (defaults to channel).
        """
        if consumer_group:
            await self._subscribe_with_group(
                channel, callback, consumer_group, consumer_name or channel,
            )
        else:
            await self._subscribe_simple(channel, callback)

    async def _subscribe_simple(
        self,
        channel: str,
        callback: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Simple stream reader — starts from the latest entry."""
        last_id = "$"  # Only new messages

        logger.info("Subscribed to stream %s (simple mode)", channel)

        while True:
            entries = await self.client.xread(
                {channel: last_id},
                count=10,
                block=STREAM_BLOCK_MS,
            )
            if not entries:
                continue

            for _stream_name, messages in entries:
                for entry_id, fields in messages:
                    last_id = entry_id
                    data = self._deserialize(fields.get("payload") or fields)
                    try:
                        await callback(data)
                    except Exception as e:
                        logger.error(
                            "Error processing stream message %s from %s: %s",
                            entry_id, channel, e,
                        )

    async def _subscribe_with_group(
        self,
        channel: str,
        callback: Callable[[dict[str, Any]], Any],
        group: str,
        consumer: str,
    ) -> None:
        """Consumer group reader with acknowledgment and dead-letter handling."""
        # Create consumer group if it doesn't exist
        try:
            await self.client.xgroup_create(channel, group, id="0", mkstream=True)
            logger.info("Created consumer group '%s' on stream %s", group, channel)
        except Exception:
            # Group already exists — that's fine
            pass

        logger.info(
            "Subscribed to stream %s (group=%s, consumer=%s)", channel, group, consumer,
        )

        while True:
            # First, reclaim any pending (unacknowledged) messages
            await self._process_pending(channel, group, consumer, callback)

            # Then read new messages
            entries = await self.client.xreadgroup(
                group, consumer,
                {channel: ">"},
                count=10,
                block=STREAM_BLOCK_MS,
            )
            if not entries:
                continue

            for _stream_name, messages in entries:
                for entry_id, fields in messages:
                    data = self._deserialize(fields.get("payload") or fields)
                    try:
                        await callback(data)
                        # Acknowledge successful processing
                        await self.client.xack(channel, group, entry_id)
                    except Exception as e:
                        logger.error(
                            "Error processing stream message %s from %s: %s",
                            entry_id, channel, e,
                        )
                        # Message stays pending for retry on next loop

    async def _process_pending(
        self,
        channel: str,
        group: str,
        consumer: str,
        callback: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Reprocess pending (unacknowledged) messages up to max delivery attempts."""
        try:
            pending = await self.client.xpending_range(
                channel, group, min="-", max="+", count=10, consumername=consumer,
            )
        except Exception:
            return

        for entry in pending:
            entry_id = entry.get("message_id") or entry[0]
            delivery_count = entry.get("times_delivered") or entry[3]

            if delivery_count > MAX_DELIVERY_ATTEMPTS:
                # Move to dead-letter stream and acknowledge
                logger.warning(
                    "Message %s exceeded max deliveries (%d), moving to dead-letter",
                    entry_id, delivery_count,
                )
                await self._move_to_dead_letter(channel, group, entry_id)
                continue

            # Re-read and retry
            messages = await self.client.xrange(channel, min=entry_id, max=entry_id)
            for _eid, fields in messages:
                data = self._deserialize(fields.get("payload") or fields)
                try:
                    await callback(data)
                    await self.client.xack(channel, group, entry_id)
                except Exception as e:
                    logger.warning(
                        "Retry %d failed for message %s: %s", delivery_count, entry_id, e,
                    )

    async def _move_to_dead_letter(
        self,
        channel: str,
        group: str,
        entry_id: str,
    ) -> None:
        """Move a failed message to the dead-letter stream and ack it."""
        dead_letter_stream = f"{channel}:dead_letter"
        try:
            messages = await self.client.xrange(channel, min=entry_id, max=entry_id)
            for _eid, fields in messages:
                await self.client.xadd(
                    dead_letter_stream,
                    {**fields, "original_id": str(entry_id), "original_stream": channel},
                    maxlen=self.max_stream_length,
                    approximate=True,
                )
            await self.client.xack(channel, group, entry_id)
            logger.info("Moved message %s to dead-letter stream %s", entry_id, dead_letter_stream)
        except Exception as e:
            logger.error("Failed to move message %s to dead-letter: %s", entry_id, e)

    async def replay(
        self,
        channel: str,
        start_id: str = "0",
        count: int = 100,
    ) -> list[dict[str, Any]]:
        """Replay messages from a stream starting at a given ID.

        Args:
            channel: Stream name.
            start_id: Starting stream entry ID ("0" for all).
            count: Maximum number of messages to return.

        Returns:
            List of deserialized message dicts.
        """
        entries = await self.client.xrange(channel, min=start_id, count=count)
        results = []
        for entry_id, fields in entries:
            data = self._deserialize(fields.get("payload") or fields)
            data["_stream_id"] = entry_id
            results.append(data)
        return results

    @staticmethod
    def _deserialize(data: Any) -> dict[str, Any]:
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8")
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                pass
        if isinstance(data, dict):
            # Try to parse the 'payload' field if present
            payload = data.get("payload")
            if payload and isinstance(payload, str):
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    pass
            return data
        return {"raw": data}
