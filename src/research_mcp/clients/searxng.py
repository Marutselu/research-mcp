"""SearXNG meta-search API client."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from research_mcp.clients.http import APIError, raise_for_status, with_retry

logger = logging.getLogger(__name__)


class SearXNGClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        base_url: str,
        semaphore: asyncio.Semaphore | None = None,
        delay_seconds: float = 3.0,
        jitter_range: tuple[float, float] = (0.25, 1.5),
    ) -> None:
        self._client = http_client
        self._base_url = base_url.rstrip("/")
        self._semaphore = semaphore
        self._delay_seconds = delay_seconds
        self._jitter_range = jitter_range
        self._last_request_time: float = 0.0

    @with_retry(max_attempts=3)
    async def search(
        self,
        query: str,
        categories: list[str] | None = None,
        time_range: str | None = None,
        language: str = "en",
        safesearch: int = 0,
        page: int = 1,
    ) -> dict[str, Any]:
        """Search via SearXNG JSON API with rate limiting."""
        # Concurrency control
        if self._semaphore:
            async with self._semaphore:
                return await self._do_search(query, categories, time_range, language, safesearch, page)
        return await self._do_search(query, categories, time_range, language, safesearch, page)

    async def _do_search(
        self,
        query: str,
        categories: list[str] | None,
        time_range: str | None,
        language: str,
        safesearch: int,
        page: int,
    ) -> dict[str, Any]:
        """Internal search implementation with delay+jitter."""
        # Delay + jitter between requests
        await self._wait_with_jitter()

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
                headers={
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                },
            )
            raise_for_status(response, source="searxng")
            return response.json()
        except httpx.ConnectError:
            raise APIError(
                f"Cannot connect to SearXNG at {self._base_url}. Is it running?",
                source="searxng",
            )

    async def _wait_with_jitter(self) -> None:
        """Enforce minimum delay between requests with random jitter."""
        elapsed = time.monotonic() - self._last_request_time
        jitter = random.uniform(*self._jitter_range)
        wait_time = self._delay_seconds + jitter
        if elapsed < wait_time:
            await asyncio.sleep(wait_time - elapsed)
        self._last_request_time = time.monotonic()
