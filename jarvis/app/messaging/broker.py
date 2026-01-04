"""Redis Pub/Sub messaging client."""
import logging
from typing import Callable

from ..db.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class MessageBroker:
    """Redis Pub/Sub wrapper for agent messaging."""

    def __init__(self):
        self.client = get_redis_client()

    async def publish(self, channel: str, message: dict) -> None:
        """Publish message to channel."""
        await self.client.publish(channel, str(message))
        logger.info(f"Published to {channel}: {message}")

    async def subscribe(self, channel: str, callback: Callable) -> None:
        """Subscribe to channel with callback."""
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        logger.info(f"Subscribed to {channel}")

        async for message in pubsub.listen():
            if message["type"] == "message":
                await callback(message["data"])
