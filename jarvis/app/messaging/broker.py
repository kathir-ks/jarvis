"""Redis Pub/Sub messaging client."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from ..db.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class MessageBroker:
    """Redis Pub/Sub wrapper for agent messaging."""

    def __init__(self):
        self.client = get_redis_client()

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Publish message to channel."""
        payload = json.dumps(message)
        await self.client.publish(channel, payload)
        logger.info("Published to %s: %s", channel, message)

    async def subscribe(self, channel: str, callback: Callable[[dict[str, Any]], Any]) -> None:
        """Subscribe to channel with callback."""
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        logger.info("Subscribed to %s", channel)

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = self._deserialize(message["data"])
            await callback(data)

    @staticmethod
    def _deserialize(data: Any) -> dict[str, Any]:
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8")
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                pass
        return {"raw": data}
