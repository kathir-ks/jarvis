"""Initialize and register all built-in tools at startup."""
from __future__ import annotations

import logging

from ..tool_registry import get_tool_registry
from .core_tools import register_core_tools
from .web_tools import register_web_tools

logger = logging.getLogger(__name__)


def initialize_tools() -> None:
    """Register all built-in tools with the global registry."""
    logger.info("Initializing built-in tools...")

    registry = get_tool_registry()

    # Register all tool modules
    register_core_tools(registry)
    register_web_tools(registry)

    tool_count = len(registry.list_tools())
    logger.info("Tool initialization complete: %d tools registered", tool_count)

    # Log registered tools
    for tool in registry.list_tools():
        logger.debug("  - %s (%s): %s", tool.name, tool.category.value, tool.description)
