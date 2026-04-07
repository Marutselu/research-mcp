"""Document extraction service: Docling + article cleanup."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.docling import DoclingClient
from research_mcp.clients.http import ServiceError
from research_mcp.config import ResearchMCPConfig
from research_mcp.models.document import ExtractedDocument

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(self, http_client: httpx.AsyncClient, config: ResearchMCPConfig) -> None:
        self._docling = DoclingClient(http_client, config.services.docling_url)
        self._config = config

    async def extract_document(
        self,
        url_or_path: str,
        extract_tables: bool = True,
        extract_images: bool = False,
    ) -> ExtractedDocument:
        """Extract document content via Docling Serve."""
        return await self._docling.convert(
            url_or_path,
            extract_tables=extract_tables,
            extract_images=extract_images,
        )

    async def extract_article(self, url: str) -> str:
        """Extract article content from a web page using readability-style extraction.

        This uses Scrapling + markdownify for content extraction, not Docling.
        """
        try:
            from research_mcp.clients.scrapling_client import ScraplingClient
            from research_mcp.services.scraper import ScraperService

            scrapling = ScraplingClient(self._config.scraping)
            scraper = ScraperService(scrapling, self._config.scraping)

            # Use the article CSS selector for main content extraction
            content = await scraper.scrape(
                url=url,
                tier="auto",
                extract_markdown=True,
                css_selector="article, main, .post-content, .article-content, .entry-content, #content",
            )

            if content and len(content.strip()) > 100:
                return content

            # Fallback: get full page without selector
            return await scraper.scrape(url=url, tier="auto", extract_markdown=True)

        except ImportError:
            raise ServiceError(
                "Article extraction requires the 'web' extras: pip install 'research-mcp[web]'"
            )
