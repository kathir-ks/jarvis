"""Vector memory service using Qdrant for long-term agent memory."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from qdrant_client.http.exceptions import UnexpectedResponse

from ..core.settings import get_settings
from ..llm.embeddings import EmbeddingProvider, get_embedding_provider

logger = logging.getLogger(__name__)


# Collection names
COLLECTION_USER_INTERACTIONS = "user_interactions"
COLLECTION_CONTENT_DISCOVERIES = "content_discoveries"
COLLECTION_AGENT_KNOWLEDGE = "agent_knowledge"

# Vector dimensions (must match embedding model)
VECTOR_DIMENSIONS = 1536


@dataclass
class MemoryEntry:
    """A single memory entry with metadata."""
    
    id: str
    content: str
    vector: list[float] | None = None
    user_id: str | None = None
    agent_id: str | None = None
    memory_type: str = "interaction"  # interaction, discovery, knowledge
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    score: float = 0.0  # Similarity score (populated on retrieval)


@dataclass
class MemorySearchResult:
    """Results from memory search."""
    
    entries: list[MemoryEntry]
    query: str
    total_found: int


class VectorMemoryService:
    """
    Service for storing and retrieving agent memories using vector embeddings.
    
    Supports:
    - User interactions (conversations, preferences)
    - Content discoveries (web pages, products, articles)
    - Agent knowledge (learned facts, patterns)
    """
    
    def __init__(
        self,
        qdrant_client: QdrantClient | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        settings = get_settings()
        
        if qdrant_client:
            self.client = qdrant_client
        else:
            self.client = QdrantClient(url=settings.qdrant_url)
        
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self._collections_initialized = False
    
    async def initialize_collections(self) -> None:
        """Create Qdrant collections if they don't exist."""
        if self._collections_initialized:
            return
        
        collections = [
            COLLECTION_USER_INTERACTIONS,
            COLLECTION_CONTENT_DISCOVERIES,
            COLLECTION_AGENT_KNOWLEDGE,
        ]
        
        for collection_name in collections:
            try:
                # Check if collection exists
                self.client.get_collection(collection_name)
                logger.debug("Collection %s already exists", collection_name)
            except (UnexpectedResponse, Exception):
                # Create collection
                logger.info("Creating collection: %s", collection_name)
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=qdrant_models.VectorParams(
                        size=VECTOR_DIMENSIONS,
                        distance=qdrant_models.Distance.COSINE,
                    ),
                )
        
        self._collections_initialized = True
        logger.info("Vector memory collections initialized")
    
    async def store_interaction(
        self,
        content: str,
        user_id: str,
        agent_id: str,
        interaction_type: str = "message",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """
        Store a user-agent interaction in vector memory.
        
        Args:
            content: The interaction content (message, response, etc.)
            user_id: User identifier
            agent_id: Agent identifier
            interaction_type: Type of interaction (message, task, response)
            metadata: Additional metadata
        
        Returns:
            The stored MemoryEntry with ID
        """
        await self.initialize_collections()
        
        # Generate embedding
        embedding_result = await self.embedding_provider.embed(content)
        
        entry_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()
        
        payload = {
            "content": content,
            "user_id": user_id,
            "agent_id": agent_id,
            "interaction_type": interaction_type,
            "timestamp": timestamp.isoformat(),
            "memory_type": "interaction",
            **(metadata or {}),
        }
        
        # Store in Qdrant
        self.client.upsert(
            collection_name=COLLECTION_USER_INTERACTIONS,
            points=[
                qdrant_models.PointStruct(
                    id=entry_id,
                    vector=embedding_result.vector,
                    payload=payload,
                )
            ],
        )
        
        logger.debug("Stored interaction memory: %s", entry_id)
        
        return MemoryEntry(
            id=entry_id,
            content=content,
            vector=embedding_result.vector,
            user_id=user_id,
            agent_id=agent_id,
            memory_type="interaction",
            metadata=payload,
            timestamp=timestamp,
        )
    
    async def store_discovery(
        self,
        content: str,
        user_id: str,
        agent_id: str,
        source: str,
        url: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """
        Store a content discovery (web page, product, article, etc.).
        
        Args:
            content: The discovered content or summary
            user_id: User identifier
            agent_id: Agent that made the discovery
            source: Source of discovery (web, api, etc.)
            url: URL if applicable
            tags: Content tags
            metadata: Additional metadata
        
        Returns:
            The stored MemoryEntry
        """
        await self.initialize_collections()
        
        embedding_result = await self.embedding_provider.embed(content)
        
        entry_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()
        
        payload = {
            "content": content,
            "user_id": user_id,
            "agent_id": agent_id,
            "source": source,
            "url": url,
            "tags": tags or [],
            "timestamp": timestamp.isoformat(),
            "memory_type": "discovery",
            **(metadata or {}),
        }
        
        self.client.upsert(
            collection_name=COLLECTION_CONTENT_DISCOVERIES,
            points=[
                qdrant_models.PointStruct(
                    id=entry_id,
                    vector=embedding_result.vector,
                    payload=payload,
                )
            ],
        )
        
        logger.debug("Stored discovery memory: %s", entry_id)
        
        return MemoryEntry(
            id=entry_id,
            content=content,
            vector=embedding_result.vector,
            user_id=user_id,
            agent_id=agent_id,
            memory_type="discovery",
            metadata=payload,
            timestamp=timestamp,
        )
    
    async def store_knowledge(
        self,
        content: str,
        agent_id: str,
        knowledge_type: str = "fact",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """
        Store agent knowledge (learned facts, patterns, preferences).
        
        Args:
            content: The knowledge content
            agent_id: Agent identifier
            knowledge_type: Type of knowledge (fact, preference, pattern)
            confidence: Confidence score (0-1)
            metadata: Additional metadata
        
        Returns:
            The stored MemoryEntry
        """
        await self.initialize_collections()
        
        embedding_result = await self.embedding_provider.embed(content)
        
        entry_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()
        
        payload = {
            "content": content,
            "agent_id": agent_id,
            "knowledge_type": knowledge_type,
            "confidence": confidence,
            "timestamp": timestamp.isoformat(),
            "memory_type": "knowledge",
            **(metadata or {}),
        }
        
        self.client.upsert(
            collection_name=COLLECTION_AGENT_KNOWLEDGE,
            points=[
                qdrant_models.PointStruct(
                    id=entry_id,
                    vector=embedding_result.vector,
                    payload=payload,
                )
            ],
        )
        
        logger.debug("Stored knowledge memory: %s", entry_id)
        
        return MemoryEntry(
            id=entry_id,
            content=content,
            vector=embedding_result.vector,
            agent_id=agent_id,
            memory_type="knowledge",
            metadata=payload,
            timestamp=timestamp,
        )
    
    async def search_interactions(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 10,
        score_threshold: float = 0.5,
    ) -> MemorySearchResult:
        """
        Search user interactions by semantic similarity.
        
        Args:
            query: Search query
            user_id: Filter by user (optional)
            agent_id: Filter by agent (optional)
            limit: Maximum results to return
            score_threshold: Minimum similarity score (0-1)
        
        Returns:
            MemorySearchResult with matching entries
        """
        return await self._search_collection(
            collection_name=COLLECTION_USER_INTERACTIONS,
            query=query,
            filters=self._build_filters(user_id=user_id, agent_id=agent_id),
            limit=limit,
            score_threshold=score_threshold,
        )
    
    async def search_discoveries(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        score_threshold: float = 0.5,
    ) -> MemorySearchResult:
        """
        Search content discoveries by semantic similarity.
        
        Args:
            query: Search query
            user_id: Filter by user (optional)
            agent_id: Filter by agent (optional)
            tags: Filter by tags (optional)
            limit: Maximum results
            score_threshold: Minimum similarity score
        
        Returns:
            MemorySearchResult with matching entries
        """
        filters = self._build_filters(user_id=user_id, agent_id=agent_id)
        
        # Add tag filter if specified
        if tags:
            tag_condition = qdrant_models.FieldCondition(
                key="tags",
                match=qdrant_models.MatchAny(any=tags),
            )
            if filters:
                filters.must.append(tag_condition)
            else:
                filters = qdrant_models.Filter(must=[tag_condition])
        
        return await self._search_collection(
            collection_name=COLLECTION_CONTENT_DISCOVERIES,
            query=query,
            filters=filters,
            limit=limit,
            score_threshold=score_threshold,
        )
    
    async def search_knowledge(
        self,
        query: str,
        agent_id: str | None = None,
        knowledge_type: str | None = None,
        limit: int = 10,
        score_threshold: float = 0.5,
    ) -> MemorySearchResult:
        """
        Search agent knowledge by semantic similarity.
        
        Args:
            query: Search query
            agent_id: Filter by agent (optional)
            knowledge_type: Filter by type (fact, preference, pattern)
            limit: Maximum results
            score_threshold: Minimum similarity score
        
        Returns:
            MemorySearchResult with matching entries
        """
        filters = self._build_filters(agent_id=agent_id)
        
        if knowledge_type:
            type_condition = qdrant_models.FieldCondition(
                key="knowledge_type",
                match=qdrant_models.MatchValue(value=knowledge_type),
            )
            if filters:
                filters.must.append(type_condition)
            else:
                filters = qdrant_models.Filter(must=[type_condition])
        
        return await self._search_collection(
            collection_name=COLLECTION_AGENT_KNOWLEDGE,
            query=query,
            filters=filters,
            limit=limit,
            score_threshold=score_threshold,
        )
    
    async def get_recent_context(
        self,
        user_id: str,
        agent_id: str,
        query: str | None = None,
        interaction_limit: int = 5,
        discovery_limit: int = 3,
        knowledge_limit: int = 3,
        recency_weight: float = 0.3,
    ) -> dict[str, list[MemoryEntry]]:
        """
        Get relevant context for agent reasoning with time-weighted scoring.

        Combines recent interactions, related discoveries, and relevant knowledge.
        Applies time decay to favor more recent memories.

        Args:
            user_id: User identifier
            agent_id: Agent identifier
            query: Optional query to focus context retrieval
            interaction_limit: Max recent interactions
            discovery_limit: Max related discoveries
            knowledge_limit: Max relevant knowledge
            recency_weight: Weight for time decay (0.0-1.0, default 0.3)
                           Higher values favor more recent memories

        Returns:
            Dict with 'interactions', 'discoveries', 'knowledge' lists
        """
        import math

        context = {
            "interactions": [],
            "discoveries": [],
            "knowledge": [],
        }

        # If no query, use a generic context query
        search_query = query or "recent context and relevant information"

        try:
            # Get recent interactions
            interactions = await self.search_interactions(
                query=search_query,
                user_id=user_id,
                agent_id=agent_id,
                limit=interaction_limit * 2,  # Get more, then re-rank
                score_threshold=0.2,  # Lower threshold for time-weighted re-ranking
            )

            # Apply time-weighted re-ranking
            now = datetime.utcnow()
            for entry in interactions.entries:
                age_days = (now - entry.timestamp).total_seconds() / 86400
                # Exponential decay: half-life of 7 days
                time_decay = math.exp(-age_days / 7)

                # Combine similarity score with time decay
                entry.score = (
                    entry.score * (1 - recency_weight) +
                    time_decay * recency_weight
                )

            # Re-sort by adjusted score and limit
            interactions.entries.sort(key=lambda e: e.score, reverse=True)
            context["interactions"] = interactions.entries[:interaction_limit]

        except Exception as e:
            logger.warning("Failed to retrieve interactions: %s", e)

        try:
            # Get related discoveries (with time weighting)
            discoveries = await self.search_discoveries(
                query=search_query,
                user_id=user_id,
                limit=discovery_limit * 2,
                score_threshold=0.2,
            )

            # Apply time-weighted re-ranking
            now = datetime.utcnow()
            for entry in discoveries.entries:
                age_days = (now - entry.timestamp).total_seconds() / 86400
                time_decay = math.exp(-age_days / 7)

                entry.score = (
                    entry.score * (1 - recency_weight) +
                    time_decay * recency_weight
                )

            discoveries.entries.sort(key=lambda e: e.score, reverse=True)
            context["discoveries"] = discoveries.entries[:discovery_limit]

        except Exception as e:
            logger.warning("Failed to retrieve discoveries: %s", e)

        try:
            # Get relevant knowledge (time decay less important for facts)
            knowledge = await self.search_knowledge(
                query=search_query,
                agent_id=agent_id,
                limit=knowledge_limit,
                score_threshold=0.4,
            )
            context["knowledge"] = knowledge.entries

        except Exception as e:
            logger.warning("Failed to retrieve knowledge: %s", e)

        logger.info(
            f"Retrieved context with time weighting (recency_weight={recency_weight}): "
            f"{len(context['interactions'])} interactions, "
            f"{len(context['discoveries'])} discoveries, "
            f"{len(context['knowledge'])} knowledge entries"
        )

        return context
    
    async def delete_by_agent(self, agent_id: str) -> int:
        """Delete all memories for an agent. Returns count deleted."""
        await self.initialize_collections()
        
        total_deleted = 0
        
        for collection in [COLLECTION_USER_INTERACTIONS, COLLECTION_CONTENT_DISCOVERIES, COLLECTION_AGENT_KNOWLEDGE]:
            try:
                result = self.client.delete(
                    collection_name=collection,
                    points_selector=qdrant_models.FilterSelector(
                        filter=qdrant_models.Filter(
                            must=[
                                qdrant_models.FieldCondition(
                                    key="agent_id",
                                    match=qdrant_models.MatchValue(value=agent_id),
                                )
                            ]
                        )
                    ),
                )
                # Note: Qdrant doesn't return count in delete, so we estimate
                logger.debug("Deleted memories from %s for agent %s", collection, agent_id)
            except Exception as e:
                logger.error("Failed to delete from %s: %s", collection, e)
        
        return total_deleted
    
    async def _search_collection(
        self,
        collection_name: str,
        query: str,
        filters: qdrant_models.Filter | None,
        limit: int,
        score_threshold: float,
    ) -> MemorySearchResult:
        """Internal method to search a collection."""
        await self.initialize_collections()
        
        # Generate query embedding
        embedding_result = await self.embedding_provider.embed(query)
        
        # Search Qdrant
        results = self.client.search(
            collection_name=collection_name,
            query_vector=embedding_result.vector,
            query_filter=filters,
            limit=limit,
            score_threshold=score_threshold,
        )
        
        entries = []
        for hit in results:
            payload = hit.payload or {}
            entries.append(MemoryEntry(
                id=str(hit.id),
                content=payload.get("content", ""),
                user_id=payload.get("user_id"),
                agent_id=payload.get("agent_id"),
                memory_type=payload.get("memory_type", "unknown"),
                metadata=payload,
                timestamp=datetime.fromisoformat(payload["timestamp"]) if payload.get("timestamp") else datetime.utcnow(),
                score=hit.score,
            ))
        
        return MemorySearchResult(
            entries=entries,
            query=query,
            total_found=len(entries),
        )
    
    def _build_filters(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
    ) -> qdrant_models.Filter | None:
        """Build Qdrant filter from parameters."""
        conditions = []
        
        if user_id:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="user_id",
                    match=qdrant_models.MatchValue(value=user_id),
                )
            )
        
        if agent_id:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="agent_id",
                    match=qdrant_models.MatchValue(value=agent_id),
                )
            )
        
        if conditions:
            return qdrant_models.Filter(must=conditions)
        return None


# Singleton instance
_vector_memory_service: VectorMemoryService | None = None


def get_vector_memory_service() -> VectorMemoryService:
    """Get or create the singleton vector memory service."""
    global _vector_memory_service
    if _vector_memory_service is None:
        _vector_memory_service = VectorMemoryService()
    return _vector_memory_service
