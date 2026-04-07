"""3-tier Scrapling scraping facade: basic → dynamic → stealth."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from research_mcp.clients.http import APIError
from research_mcp.config import ScrapingConfig

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    html: str
    url: str
    status: int
    tier_used: str


class ScraplingClient:
    def __init__(self, config: ScrapingConfig) -> None:
        self._config = config

    async def fetch(self, url: str, tier: str = "auto") -> ScrapeResult:
        """Fetch a URL using the specified scraping tier.

        tier='auto' will try basic first, then escalate on failure.
        """
        if tier == "auto" and self._config.auto_escalate:
            return await self._fetch_with_escalation(url)

        tiers = {"basic": self._fetch_basic, "dynamic": self._fetch_dynamic, "stealth": self._fetch_stealth}
        fetch_fn = tiers.get(tier, self._fetch_basic)
        return await fetch_fn(url)

    async def _fetch_with_escalation(self, url: str) -> ScrapeResult:
        """Try basic first, escalate to dynamic, then stealth on failure."""
        for tier_name, fetch_fn in [
            ("basic", self._fetch_basic),
            ("dynamic", self._fetch_dynamic),
            ("stealth", self._fetch_stealth),
        ]:
            try:
                result = await fetch_fn(url)
                if result.html and len(result.html.strip()) > 100:
                    return result
                logger.info("Tier '%s' returned insufficient content for %s, escalating", tier_name, url)
            except Exception as e:
                logger.info("Tier '%s' failed for %s: %s, escalating", tier_name, url, e)
                continue

        raise APIError(f"All scraping tiers failed for {url}", source="scrapling")

    async def _fetch_basic(self, url: str) -> ScrapeResult:
        """Tier 1: Fast HTTP with TLS fingerprint impersonation."""
        from scrapling import Fetcher

        fetcher = Fetcher(auto_match=False)
        response = await asyncio.to_thread(fetcher.get, url, stealthy_headers=True)
        return ScrapeResult(
            html=response.html_content if hasattr(response, "html_content") else str(response.text),
            url=url,
            status=response.status if hasattr(response, "status") else 200,
            tier_used="basic",
        )

    async def _fetch_dynamic(self, url: str) -> ScrapeResult:
        """Tier 2: Playwright/Chromium, renders JavaScript."""
        from scrapling import PlayWrightFetcher

        fetcher = PlayWrightFetcher()
        response = await asyncio.to_thread(
            fetcher.fetch,
            url,
            headless=True,
            wait_selector_timeout=self._config.timeout_seconds * 1000,
        )
        return ScrapeResult(
            html=response.html_content if hasattr(response, "html_content") else str(response.text),
            url=url,
            status=response.status if hasattr(response, "status") else 200,
            tier_used="dynamic",
        )

    async def _fetch_stealth(self, url: str) -> ScrapeResult:
        """Tier 3: Camoufox stealth browser, anti-bot bypass."""
        from scrapling import StealthyFetcher

        fetcher = StealthyFetcher()
        response = await asyncio.to_thread(
            fetcher.fetch,
            url,
            headless=True,
            block_webrtc=True,
        )
        return ScrapeResult(
            html=response.html_content if hasattr(response, "html_content") else str(response.text),
            url=url,
            status=response.status if hasattr(response, "status") else 200,
            tier_used="stealth",
        )
