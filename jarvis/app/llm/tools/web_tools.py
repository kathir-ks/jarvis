"""Web-related tools for agent capabilities."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

import httpx

from ..tool_registry import (
    ToolDefinition,
    ToolParameter,
    ToolCategory,
    ToolRegistry,
    get_tool_registry,
)

logger = logging.getLogger(__name__)


# Tool Definitions
WEB_SEARCH_TOOL = ToolDefinition(
    name="web_search",
    description="Search the web for information. Returns a list of search results with titles, URLs, and snippets.",
    category=ToolCategory.WEB,
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="The search query",
            required=True,
        ),
        ToolParameter(
            name="num_results",
            type="number",
            description="Number of results to return (max 10)",
            required=False,
            default=5,
        ),
    ],
    returns="array",
    returns_description="Array of search results with title, url, and snippet",
    timeout_seconds=15,
)


READ_URL_TOOL = ToolDefinition(
    name="read_url",
    description="Fetch and extract text content from a URL. Useful for reading web pages, articles, or documentation.",
    category=ToolCategory.WEB,
    parameters=[
        ToolParameter(
            name="url",
            type="string",
            description="The URL to fetch content from",
            required=True,
        ),
        ToolParameter(
            name="max_length",
            type="number",
            description="Maximum characters to return",
            required=False,
            default=5000,
        ),
    ],
    returns="object",
    returns_description="Object with url, title, and content fields",
    timeout_seconds=30,
)


# Tool Handlers
async def web_search_handler(params: dict[str, Any]) -> list[dict[str, str]]:
    """Execute web search using DuckDuckGo HTML search."""
    query = params["query"]
    num_results = min(params.get("num_results", 5), 10)

    logger.info("Executing web search: %s", query)

    # Use DuckDuckGo HTML search (no API key required)
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            search_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; JarvisAgent/1.0)"},
            follow_redirects=True,
        )
        response.raise_for_status()

    # Parse results from HTML
    results = _parse_duckduckgo_html(response.text, num_results)

    logger.info("Web search returned %d results", len(results))
    return results


def _parse_duckduckgo_html(html: str, max_results: int) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML search results."""
    results = []

    # Simple parsing without heavy dependencies
    # Look for result blocks
    import re

    # Find result links
    link_pattern = r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>'
    snippet_pattern = r'<a[^>]+class="result__snippet"[^>]*>([^<]+(?:<[^>]+>[^<]*</[^>]+>[^<]*)*)</a>'

    links = re.findall(link_pattern, html)
    snippets = re.findall(snippet_pattern, html)

    for i, (url, title) in enumerate(links[:max_results]):
        snippet = ""
        if i < len(snippets):
            # Clean HTML from snippet
            snippet = re.sub(r'<[^>]+>', '', snippets[i])

        # Clean up URL (DuckDuckGo uses redirects)
        if "uddg=" in url:
            url_match = re.search(r'uddg=([^&]+)', url)
            if url_match:
                from urllib.parse import unquote
                url = unquote(url_match.group(1))

        results.append({
            "title": title.strip(),
            "url": url,
            "snippet": snippet.strip(),
        })

    return results


async def read_url_handler(params: dict[str, Any]) -> dict[str, Any]:
    """Fetch and extract text content from a URL."""
    url = params["url"]
    max_length = params.get("max_length", 5000)

    logger.info("Fetching URL: %s", url)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; JarvisAgent/1.0)"},
            follow_redirects=True,
            timeout=20.0,
        )
        response.raise_for_status()

    content_type = response.headers.get("content-type", "")

    if "text/html" in content_type:
        title, content = _extract_html_content(response.text)
    else:
        title = url
        content = response.text

    # Truncate if needed
    if len(content) > max_length:
        content = content[:max_length] + "... [truncated]"

    return {
        "url": str(response.url),
        "title": title,
        "content": content,
        "content_type": content_type,
    }


def _extract_html_content(html: str) -> tuple[str, str]:
    """Extract title and main text content from HTML."""
    import re

    # Extract title
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ""

    # Remove script and style tags
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)

    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # Decode HTML entities
    import html as html_module
    text = html_module.unescape(text)

    return title, text


def register_web_tools(registry: ToolRegistry | None = None) -> None:
    """Register all web-related tools."""
    registry = registry or get_tool_registry()

    registry.register(WEB_SEARCH_TOOL, web_search_handler)
    registry.register(READ_URL_TOOL, read_url_handler)

    logger.info("Web tools registered")
