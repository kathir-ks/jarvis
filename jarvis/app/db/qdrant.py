"""Qdrant vector DB client."""
from qdrant_client import QdrantClient

from ..core.settings import get_settings

_qdrant_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        settings = get_settings()
        _qdrant_client = QdrantClient(url=str(settings.qdrant_url))
    return _qdrant_client


def close_qdrant_client() -> None:
    global _qdrant_client
    if _qdrant_client is not None:
        _qdrant_client.close()
        _qdrant_client = None
