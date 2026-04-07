"""Scraper service: 3-tier escalation, HTML → markdown, pagination."""

from __future__ import annotations

import logging

from research_mcp.clients.scrapling_client import ScraplingClient
from research_mcp.config import ScrapingConfig

logger = logging.getLogger(__name__)


class ScraperService:
    def __init__(self, scrapling_client: ScraplingClient, config: ScrapingConfig) -> None:
        self._client = scrapling_client
        self._config = config

    async def scrape(
        self,
        url: str,
        tier: str = "auto",
        extract_markdown: bool = True,
        css_selector: str | None = None,
    ) -> str:
        """Scrape a URL and return content as text or markdown."""
        result = await self._client.fetch(url, tier=tier)
        html = result.html

        if css_selector:
            html = self._extract_selector(html, css_selector)

        if extract_markdown:
            return self._html_to_markdown(html)

        return html

    def _extract_selector(self, html: str, selector: str) -> str:
        """Extract content matching a CSS selector."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")
            elements = soup.select(selector)
            if elements:
                return "\n".join(str(el) for el in elements)
            return html
        except ImportError:
            logger.warning("beautifulsoup4 not available for CSS selection, returning full HTML")
            return html

    def _html_to_markdown(self, html: str) -> str:
        """Convert HTML to clean markdown."""
        try:
            from markdownify import markdownify

            # First strip scripts and styles
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html, "lxml")
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                html = str(soup)
            except ImportError:
                pass

            md = markdownify(html, heading_style="ATX", strip=["img"])
            # Clean up excessive whitespace
            lines = md.split("\n")
            cleaned = []
            blank_count = 0
            for line in lines:
                stripped = line.rstrip()
                if not stripped:
                    blank_count += 1
                    if blank_count <= 2:
                        cleaned.append("")
                else:
                    blank_count = 0
                    cleaned.append(stripped)

            return "\n".join(cleaned).strip()
        except ImportError:
            logger.warning("markdownify not available, returning raw HTML")
            return html
