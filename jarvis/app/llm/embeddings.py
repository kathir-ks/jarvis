"""Embedding generation for vector memory."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from ..core.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EmbeddingResult:
    """Result from embedding generation."""
    
    vector: list[float]
    model: str
    tokens_used: int
    dimensions: int


class EmbeddingProvider:
    """Generates embeddings using OpenAI's embedding models."""
    
    DEFAULT_MODEL = "text-embedding-3-small"
    DIMENSIONS = 1536  # Default for text-embedding-3-small
    
    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        if not self.api_key:
            raise ValueError("OpenAI API key required for embeddings")
        
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = model or self.DEFAULT_MODEL
    
    async def embed(self, text: str) -> EmbeddingResult:
        """Generate embedding for a single text."""
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        
        logger.debug("Generating embedding for text (length=%d)", len(text))
        
        response = await self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        
        embedding = response.data[0].embedding
        tokens = response.usage.total_tokens if response.usage else 0
        
        return EmbeddingResult(
            vector=embedding,
            model=self.model,
            tokens_used=tokens,
            dimensions=len(embedding),
        )
    
    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []
        
        # Filter out empty texts
        valid_texts = [t for t in texts if t and t.strip()]
        if not valid_texts:
            return []
        
        logger.debug("Generating embeddings for %d texts", len(valid_texts))
        
        response = await self.client.embeddings.create(
            model=self.model,
            input=valid_texts,
        )
        
        tokens_per_text = (response.usage.total_tokens // len(valid_texts)) if response.usage else 0
        
        results = []
        for item in response.data:
            results.append(EmbeddingResult(
                vector=item.embedding,
                model=self.model,
                tokens_used=tokens_per_text,
                dimensions=len(item.embedding),
            ))
        
        return results


# Singleton instance
_embedding_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """Get or create the singleton embedding provider."""
    global _embedding_provider
    if _embedding_provider is None:
        _embedding_provider = EmbeddingProvider()
    return _embedding_provider
