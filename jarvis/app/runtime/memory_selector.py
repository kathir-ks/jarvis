"""
Memory Selector Service

Intelligently selects the most relevant memories from short-term buffer
using relevance scoring based on:
- Recency (newer items prioritized)
- Semantic similarity (keyword matching)
- Role importance (user/assistant > tool/system)
- Token budget constraints
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class MemorySelector:
    """
    Intelligent memory selection with relevance scoring.

    Selects most relevant memories from short-term buffer within
    token budget constraints.
    """

    def __init__(self):
        """Initialize memory selector."""
        # Role importance weights
        self.role_weights = {
            "user": 1.0,       # User messages most important
            "assistant": 0.8,  # Assistant responses important
            "tool": 0.6,       # Tool results moderately important
            "system": 0.5,     # System messages least important
            "note": 0.5,       # Internal notes least important
        }

    def select_short_term_memories(
        self,
        memories: list[dict[str, Any]],
        query: str,
        max_count: int = 10,
        max_tokens: int = 2000,
        estimate_tokens_func: Callable[[Any], int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Select most relevant short-term memories.

        Args:
            memories: List of memory items from short-term buffer
            query: Current user query for relevance scoring
            max_count: Maximum number of memories to return
            max_tokens: Maximum token budget for selected memories
            estimate_tokens_func: Function to estimate tokens (optional)

        Returns:
            List of selected memory items, ordered by relevance
        """
        if not memories:
            return []

        # Score each memory
        scored_memories = []
        for i, memory in enumerate(memories):
            score = self._calculate_relevance_score(
                memory=memory,
                query=query,
                position=i,
                total=len(memories),
            )
            scored_memories.append((score, memory))

        # Sort by score (highest first)
        scored_memories.sort(key=lambda x: x[0], reverse=True)

        # Select top items within budget
        selected = []
        token_count = 0

        for score, memory in scored_memories:
            # Check if we've hit count limit
            if len(selected) >= max_count:
                break

            # Estimate tokens for this memory
            if estimate_tokens_func:
                memory_tokens = estimate_tokens_func(memory)
            else:
                memory_tokens = self._estimate_tokens_simple(memory)

            # Check if adding this memory would exceed budget
            if token_count + memory_tokens > max_tokens:
                logger.debug(
                    f"Stopping memory selection - would exceed budget "
                    f"({token_count + memory_tokens} > {max_tokens})"
                )
                break

            # Add memory to selection
            selected.append(memory)
            token_count += memory_tokens

        logger.info(
            f"Selected {len(selected)}/{len(memories)} memories "
            f"using {token_count}/{max_tokens} tokens"
        )

        return selected

    def _calculate_relevance_score(
        self,
        memory: dict[str, Any],
        query: str,
        position: int,
        total: int,
    ) -> float:
        """
        Calculate relevance score for a memory item.

        Combines multiple factors:
        1. Recency: More recent items scored higher
        2. Semantic similarity: Keyword overlap with query
        3. Role importance: User/assistant more important than system/tool

        Args:
            memory: Memory item to score
            query: Current query for semantic matching
            position: Position in memory buffer (0 = oldest)
            total: Total number of memories

        Returns:
            Relevance score (0.0 to 1.0, higher is more relevant)
        """
        # 1. Recency score (0.0 oldest to 1.0 newest)
        recency_score = position / max(total - 1, 1)

        # 2. Semantic similarity (keyword matching)
        semantic_score = self._calculate_semantic_similarity(memory, query)

        # 3. Role importance
        role = memory.get("role", "note")
        role_score = self.role_weights.get(role, 0.5)

        # 4. Content length bonus (longer = more informative, up to a point)
        content = str(memory.get("content", ""))
        length_score = min(len(content) / 500, 1.0)  # Cap at 500 chars

        # Weighted combination
        final_score = (
            recency_score * 0.4 +      # 40% weight on recency
            semantic_score * 0.3 +     # 30% weight on semantic match
            role_score * 0.2 +         # 20% weight on role importance
            length_score * 0.1         # 10% weight on content length
        )

        return final_score

    def _calculate_semantic_similarity(
        self,
        memory: dict[str, Any],
        query: str,
    ) -> float:
        """
        Calculate semantic similarity using simple keyword matching.

        Args:
            memory: Memory item
            query: Query string

        Returns:
            Similarity score (0.0 to 1.0)
        """
        if not query:
            return 0.5  # Neutral score if no query

        # Extract content from memory
        content = str(memory.get("content", ""))

        # Normalize and tokenize
        query_words = set(self._tokenize(query.lower()))
        content_words = set(self._tokenize(content.lower()))

        if not query_words:
            return 0.5

        # Calculate overlap
        overlap = len(query_words & content_words)
        max_possible = len(query_words)

        # Jaccard similarity
        union = len(query_words | content_words)
        if union == 0:
            return 0.0

        jaccard = overlap / union

        # Also consider coverage of query words
        coverage = overlap / max_possible if max_possible > 0 else 0.0

        # Combine both metrics
        similarity = (jaccard * 0.5) + (coverage * 0.5)

        return min(similarity, 1.0)

    def _tokenize(self, text: str) -> list[str]:
        """
        Simple tokenization for keyword matching.

        Args:
            text: Text to tokenize

        Returns:
            List of tokens
        """
        # Remove punctuation and split on whitespace
        import re
        # Keep alphanumeric and spaces
        cleaned = re.sub(r'[^a-z0-9\s]', ' ', text)
        tokens = cleaned.split()

        # Filter out very short tokens and common stop words
        stop_words = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "has", "have", "had", "do", "does", "did", "will", "would",
            "can", "could", "should", "may", "might", "must",
            "i", "you", "he", "she", "it", "we", "they",
            "in", "on", "at", "to", "for", "of", "with", "by",
        }

        return [
            token for token in tokens
            if len(token) > 2 and token not in stop_words
        ]

    def _estimate_tokens_simple(self, memory: dict[str, Any]) -> int:
        """
        Simple token estimation (4 chars ≈ 1 token).

        Args:
            memory: Memory item

        Returns:
            Estimated token count
        """
        content = str(memory.get("content", ""))
        role = str(memory.get("role", ""))

        # Content tokens
        content_tokens = len(content) // 4

        # Add overhead for structure
        overhead = 10  # Role, timestamp, etc.

        return content_tokens + overhead

    def select_by_importance(
        self,
        memories: list[dict[str, Any]],
        min_importance: float = 0.5,
    ) -> list[dict[str, Any]]:
        """
        Select memories above a minimum importance threshold.

        Useful for filtering out low-value memories before further processing.

        Args:
            memories: List of memory items
            min_importance: Minimum importance score (0.0 to 1.0)

        Returns:
            Filtered list of memories
        """
        filtered = []

        for memory in memories:
            role = memory.get("role", "note")
            role_score = self.role_weights.get(role, 0.5)

            # Simple importance based on role
            if role_score >= min_importance:
                filtered.append(memory)

        return filtered

    def deduplicate_memories(
        self,
        memories: list[dict[str, Any]],
        similarity_threshold: float = 0.9,
    ) -> list[dict[str, Any]]:
        """
        Remove duplicate or highly similar memories.

        Args:
            memories: List of memory items
            similarity_threshold: Threshold for considering items duplicates

        Returns:
            Deduplicated list of memories
        """
        if not memories:
            return []

        unique = [memories[0]]  # Start with first item

        for memory in memories[1:]:
            # Check similarity with all existing unique items
            is_duplicate = False

            for existing in unique:
                similarity = self._calculate_memory_similarity(memory, existing)
                if similarity >= similarity_threshold:
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique.append(memory)

        logger.info(f"Deduplicated {len(memories)} memories to {len(unique)}")
        return unique

    def _calculate_memory_similarity(
        self,
        memory1: dict[str, Any],
        memory2: dict[str, Any],
    ) -> float:
        """
        Calculate similarity between two memory items.

        Args:
            memory1: First memory
            memory2: Second memory

        Returns:
            Similarity score (0.0 to 1.0)
        """
        content1 = str(memory1.get("content", "")).lower()
        content2 = str(memory2.get("content", "")).lower()

        # Simple character-level similarity
        if content1 == content2:
            return 1.0

        # Tokenize and compare
        tokens1 = set(self._tokenize(content1))
        tokens2 = set(self._tokenize(content2))

        if not tokens1 or not tokens2:
            return 0.0

        # Jaccard similarity
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)

        return intersection / union if union > 0 else 0.0


# Global singleton
_memory_selector_instance: MemorySelector | None = None


def get_memory_selector() -> MemorySelector:
    """Get global MemorySelector instance (singleton)."""
    global _memory_selector_instance
    if _memory_selector_instance is None:
        _memory_selector_instance = MemorySelector()
    return _memory_selector_instance
