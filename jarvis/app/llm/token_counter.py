"""
Token Counter Service

Provides token counting functionality for different LLM providers
to prevent context window overflow and enable intelligent budget management.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Model context windows (in tokens)
MODEL_CONTEXT_WINDOWS = {
    # OpenAI models
    "gpt-4": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-3.5-turbo": 16_385,
    "gpt-3.5-turbo-16k": 16_385,

    # Gemini models
    "gemini-1.5-pro": 2_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-2.0-flash-exp": 1_000_000,
    "gemini-2.5-flash-lite": 1_000_000,

    # Anthropic models
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3-5-sonnet": 200_000,

    # Default fallback
    "default": 8_000,
}


class TokenCounter:
    """
    Token counter for multiple LLM providers.

    Provides accurate token counting for OpenAI models (using tiktoken)
    and approximations for other providers.
    """

    def __init__(self):
        """Initialize token counter with optional tiktoken support."""
        self.tiktoken_available = False
        self._tiktoken_cache = {}

        try:
            import tiktoken
            self.tiktoken = tiktoken
            self.tiktoken_available = True
            logger.info("tiktoken available for accurate OpenAI token counting")
        except ImportError:
            logger.warning(
                "tiktoken not available - using approximation for OpenAI models. "
                "Install with: pip install tiktoken"
            )

    def count_tokens(self, text: str | dict[str, Any], model: str) -> int:
        """
        Count tokens for given text and model.

        Args:
            text: Text to count tokens for (string or message dict)
            model: Model name to use for counting

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        # Handle dict input (message format)
        if isinstance(text, dict):
            text = self._dict_to_string(text)

        # Normalize model name
        model_lower = model.lower()

        # OpenAI models - use tiktoken if available
        if model_lower.startswith("gpt"):
            if self.tiktoken_available:
                return self._count_openai_tokens(text, model)
            else:
                # Fallback approximation: 4 characters ≈ 1 token
                return len(text) // 4

        # Gemini models - approximation (4 chars ≈ 1 token)
        elif model_lower.startswith("gemini"):
            return len(text) // 4

        # Anthropic models - approximation (3.5 chars ≈ 1 token, slightly more efficient)
        elif model_lower.startswith("claude"):
            return int(len(text) / 3.5)

        # Default approximation
        else:
            return len(text) // 4

    def _count_openai_tokens(self, text: str, model: str) -> int:
        """
        Count tokens using tiktoken for OpenAI models.

        Args:
            text: Text to count
            model: OpenAI model name

        Returns:
            Accurate token count
        """
        try:
            # Get encoding for model (with caching)
            if model not in self._tiktoken_cache:
                try:
                    encoding = self.tiktoken.encoding_for_model(model)
                except KeyError:
                    # Fallback to cl100k_base for newer models
                    encoding = self.tiktoken.get_encoding("cl100k_base")
                self._tiktoken_cache[model] = encoding
            else:
                encoding = self._tiktoken_cache[model]

            return len(encoding.encode(text))

        except Exception as e:
            logger.warning(f"Error counting tokens with tiktoken: {e}. Using approximation.")
            return len(text) // 4

    def _dict_to_string(self, data: dict[str, Any]) -> str:
        """
        Convert dict/message to string for token counting.

        Args:
            data: Dictionary (typically a message)

        Returns:
            String representation
        """
        if "content" in data:
            content = data["content"]
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                # Handle multi-part content (e.g., image + text)
                return " ".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in content
                )

        # Fallback: stringify the whole dict
        return str(data)

    def count_messages_tokens(self, messages: list[dict[str, Any]], model: str) -> int:
        """
        Count tokens for a list of messages.

        Args:
            messages: List of message dicts
            model: Model name

        Returns:
            Total token count including message formatting overhead
        """
        total = 0

        for message in messages:
            # Count content tokens
            total += self.count_tokens(message, model)

            # Add overhead for message formatting
            # OpenAI format adds ~4 tokens per message
            total += 4

            # Add overhead for role
            if "role" in message:
                total += 1

            # Add overhead for name (if present)
            if "name" in message:
                total += 1

        # Add overhead for priming the assistant response
        total += 3

        return total

    def get_context_window(self, model: str) -> int:
        """
        Get context window size for a model.

        Args:
            model: Model name

        Returns:
            Context window size in tokens
        """
        model_lower = model.lower()

        # Exact match
        if model_lower in MODEL_CONTEXT_WINDOWS:
            return MODEL_CONTEXT_WINDOWS[model_lower]

        # Partial match (e.g., "gpt-4-0613" matches "gpt-4")
        for model_key in MODEL_CONTEXT_WINDOWS:
            if model_lower.startswith(model_key):
                return MODEL_CONTEXT_WINDOWS[model_key]

        # Default fallback
        logger.warning(
            f"Unknown model '{model}', using default context window "
            f"of {MODEL_CONTEXT_WINDOWS['default']} tokens"
        )
        return MODEL_CONTEXT_WINDOWS["default"]

    def estimate_tool_tokens(self, tools: list[dict[str, Any]], model: str) -> int:
        """
        Estimate tokens used by tool definitions.

        Args:
            tools: List of tool definition dicts
            model: Model name

        Returns:
            Estimated token count for all tools
        """
        if not tools:
            return 0

        total = 0
        for tool in tools:
            # Convert tool to string representation
            tool_str = str(tool)
            total += self.count_tokens(tool_str, model)

        # Add overhead for function calling format
        total += len(tools) * 10  # ~10 tokens overhead per tool

        return total

    def fits_in_context(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        safety_margin: float = 0.95,
    ) -> bool:
        """
        Check if messages + tools fit in model's context window.

        Args:
            messages: List of messages
            tools: List of tool definitions (optional)
            model: Model name
            safety_margin: Use this fraction of context window (0.0-1.0)

        Returns:
            True if everything fits, False otherwise
        """
        context_window = self.get_context_window(model)
        max_tokens = int(context_window * safety_margin)

        # Count message tokens
        message_tokens = self.count_messages_tokens(messages, model)

        # Count tool tokens
        tool_tokens = 0
        if tools:
            tool_tokens = self.estimate_tool_tokens(tools, model)

        total_tokens = message_tokens + tool_tokens

        return total_tokens <= max_tokens

    def get_token_budget_breakdown(
        self,
        model: str,
        safety_margin: float = 0.95,
    ) -> dict[str, int]:
        """
        Get recommended token budget breakdown for different components.

        Args:
            model: Model name
            safety_margin: Use this fraction of context window

        Returns:
            Dict with budget allocations:
                - total_window: Total context window
                - available: Available after safety margin
                - system: Recommended system prompt budget
                - tools: Recommended tools budget
                - short_term: Recommended short-term memory budget
                - long_term: Recommended long-term memory budget
                - current: Recommended current message budget
                - reserve: Reserved buffer
        """
        total_window = self.get_context_window(model)
        available = int(total_window * safety_margin)

        return {
            "total_window": total_window,
            "available": available,
            "system": int(available * 0.20),     # 20% for system prompt
            "tools": int(available * 0.30),      # 30% for tool definitions
            "short_term": int(available * 0.20), # 20% for short-term memory
            "long_term": int(available * 0.15),  # 15% for long-term memory
            "current": int(available * 0.10),    # 10% for current message
            "reserve": int(available * 0.05),    # 5% reserve buffer
        }


# Global singleton instance
_token_counter_instance: TokenCounter | None = None


def get_token_counter() -> TokenCounter:
    """Get global TokenCounter instance (singleton)."""
    global _token_counter_instance
    if _token_counter_instance is None:
        _token_counter_instance = TokenCounter()
    return _token_counter_instance
