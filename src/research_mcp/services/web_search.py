"""Web search service: SearXNG orchestration with domain filtering."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from research_mcp.clients.searxng import SearXNGClient
from research_mcp.config import DomainFilterConfig
from research_mcp.models.search import NormalizedResult, SearchResponse

logger = logging.getLogger(__name__)


class WebSearchService:
    def __init__(self, searxng_client: SearXNGClient, domain_config: DomainFilterConfig) -> None:
        self._searxng = searxng_client
        self._domains = domain_config

    async def search(
        self,
        query: str,
        categories: list[str] | None = None,
        time_range: str | None = None,
        max_results: int = 10,
    ) -> SearchResponse:
        """Search via SearXNG with domain filtering."""
        raw = await self._searxng.search(
            query=query,
            categories=categories,
            time_range=time_range,
        )

        results = []
        for item in raw.get("results", []):
            url = item.get("url", "")

            # Apply domain filtering
            if not self._is_allowed(url):
                continue

            results.append(
                NormalizedResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("content", ""),
                    source="searxng",
                    content_type=_infer_content_type(item),
                    date=item.get("publishedDate"),
                    score=item.get("score"),
                    metadata={
                        "engine": item.get("engine", ""),
                        "category": item.get("category", ""),
                    },
                )
            )

            if len(results) >= max_results:
                break

        return SearchResponse(
            results=results,
            total=len(results),
            query=query,
            has_more=len(raw.get("results", [])) > max_results,
        )

    def _is_allowed(self, url: str) -> bool:
        """Check URL against blocklist/allowlist."""
        if not url:
            return True

        domain = urlparse(url).netloc.lower()
        # Strip www. prefix for matching
        if domain.startswith("www."):
            domain = domain[4:]

        if self._domains.blocklist:
            for blocked in self._domains.blocklist:
                if domain == blocked or domain.endswith(f".{blocked}"):
                    return False

        if self._domains.allowlist:
            for allowed in self._domains.allowlist:
                if domain == allowed or domain.endswith(f".{allowed}"):
                    return True
            return False  # Allowlist is exclusive

        return True


def _infer_content_type(item: dict[str, Any]) -> str:
    """Infer content type from SearXNG result."""
    category = item.get("category", "")
    if category == "videos":
        return "video"
    if category == "images":
        return "image"
    if category == "news":
        return "news"
    if category == "science":
        return "paper"
    return "webpage"
