"""Web search and browsing tools for MASTERMIND v2."""

import os
from typing import Optional
from loguru import logger

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


async def search_web(query: str) -> str:
    """Perform a Google search via Serper API."""
    if not HAS_HTTPX:
        return "Error: httpx not available"
    api_key = os.environ.get("SERPER_API_KEY", "")
    if not api_key:
        return "Error: SERPER_API_KEY not set"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                json={"q": query},
                headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                timeout=30.0,
            )
            data = resp.json()
            results = data.get("organic", [])
            out = []
            for r in results[:10]:
                out.append(f"**{r.get('title', '')}**\n{r.get('snippet', '')}\n{r.get('link', '')}")
            return '\n\n'.join(out) if out else f"No results for: {query}"
    except Exception as e:
        return f"Search error: {e}"


async def browse_url(url: str, query: str = "") -> str:
    """Fetch and extract content from a URL."""
    if not HAS_HTTPX:
        return "Error: httpx not available"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=30.0, follow_redirects=True)
            text = resp.text[:15000]
            if query:
                # Simple relevance filter: find paragraphs containing query terms
                terms = query.lower().split()
                relevant = [line for line in text.split('\n') if any(t in line.lower() for t in terms)]
                if relevant:
                    text = '\n'.join(relevant[:500])
            return f"URL: {url}\nStatus: {resp.status_code}\n\n{text[:10000]}"
    except Exception as e:
        return f"Browse error: {e}"


TOOL_DEFINITIONS = [
    ("search_web", search_web, "Search the web using Google via Serper API", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query phrase"},
        },
        "required": ["query"],
    }),
    ("browse_url", browse_url, "Fetch and extract content from a URL", {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to fetch"},
            "query": {"type": "string", "description": "Optional query to filter relevant content"},
        },
        "required": ["url"],
    }),
]


def register_all(registry):
    for name, func, desc, params in TOOL_DEFINITIONS:
        registry.register_function(func, name, desc, params)
    logger.info(f"Registered {len(TOOL_DEFINITIONS)} search tools")
