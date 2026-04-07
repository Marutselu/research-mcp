"""Wikipedia REST API client."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import NotFoundError, fetch_json, with_retry
from research_mcp.models.search import NormalizedResult, SearchResponse

logger = logging.getLogger(__name__)

API_BASE = "https://en.wikipedia.org/api/rest_v1"
ACTION_API = "https://en.wikipedia.org/w/api.php"


class WikipediaClient:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    @with_retry(max_attempts=2)
    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        """Search Wikipedia articles."""
        data = await fetch_json(
            self._client,
            ACTION_API,
            source="wikipedia",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": max_results,
                "format": "json",
                "utf8": "1",
            },
        )

        results = []
        for item in data.get("query", {}).get("search", []):
            import re

            snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
            results.append(
                NormalizedResult(
                    title=item.get("title", ""),
                    url=f"https://en.wikipedia.org/wiki/{item.get('title', '').replace(' ', '_')}",
                    snippet=snippet,
                    source="wikipedia",
                    content_type="encyclopedia",
                    date=item.get("timestamp"),
                )
            )

        return SearchResponse(
            results=results,
            total=data.get("query", {}).get("searchinfo", {}).get("totalhits", len(results)),
            query=query,
        )

    @with_retry(max_attempts=2)
    async def get_article(self, title: str) -> str:
        """Get article content as HTML, then convert to markdown-ish text."""
        import re
        from urllib.parse import quote

        encoded_title = quote(title.replace(" ", "_"), safe="/:@")

        try:
            response = await self._client.get(
                f"{API_BASE}/page/html/{encoded_title}",
                headers={"Accept": "text/html"},
            )
            if response.status_code == 404:
                raise NotFoundError(f"Wikipedia article not found: {title}", source="wikipedia")
            response.raise_for_status()
            html = response.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundError(f"Wikipedia article not found: {title}", source="wikipedia")
            raise

        # Convert to markdown
        try:
            from markdownify import markdownify

            md = markdownify(html, heading_style="ATX", strip=["img", "sup"])
            # Clean up
            md = re.sub(r"\n{3,}", "\n\n", md)
            return md.strip()
        except ImportError:
            # Fallback: strip HTML tags
            text = re.sub(r"<[^>]+>", "", html)
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()
