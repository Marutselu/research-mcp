"""SearXNG meta-search API client."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from research_mcp.clients.http import APIError, raise_for_status

logger = logging.getLogger(__name__)


class SearXNGClient:
    def __init__(self, http_client: httpx.AsyncClient, base_url: str) -> None:
        self._client = http_client
        self._base_url = base_url.rstrip("/")

    async def search(
        self,
        query: str,
        categories: list[str] | None = None,
        time_range: str | None = None,
        language: str = "en",
        safesearch: int = 0,
        page: int = 1,
    ) -> dict[str, Any]:
        """Search via SearXNG JSON API."""
        data: dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": language,
            "safesearch": str(safesearch),
            "pageno": str(page),
        }
        if categories:
            data["categories"] = ",".join(categories)
        if time_range:
            data["time_range"] = time_range

        try:
            response = await self._client.post(
                f"{self._base_url}/search",
                data=data,
                headers={"Accept": "application/json"},
            )
            raise_for_status(response, source="searxng")
            return response.json()
        except httpx.ConnectError:
            raise APIError(
                f"Cannot connect to SearXNG at {self._base_url}. Is it running?",
                source="searxng",
            )
