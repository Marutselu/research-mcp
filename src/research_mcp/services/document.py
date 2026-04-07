"""Document extraction service: pymupdf (fast) → Docling (heavy) fallback."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import APIError, ServiceError
from research_mcp.config import ResearchMCPConfig
from research_mcp.models.document import ExtractedDocument

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(self, http_client: httpx.AsyncClient, config: ResearchMCPConfig) -> None:
        self._http = http_client
        self._config = config

        # Try to initialize pymupdf (lightweight, preferred)
        self._pymupdf = None
        try:
            from research_mcp.clients.pdf import PyMuPDFClient, is_available

            if is_available():
                self._pymupdf = PyMuPDFClient(http_client)
                logger.info("PyMuPDF available for fast PDF extraction")
        except ImportError:
            pass

        # Docling is always available as a remote service (if configured)
        self._docling = None
        if config.services.docling_url:
            from research_mcp.clients.docling import DoclingClient

            self._docling = DoclingClient(http_client, config.services.docling_url)

    async def extract_document(
        self,
        url_or_path: str,
        extract_tables: bool = True,
        extract_images: bool = False,
    ) -> ExtractedDocument:
        """Extract document content. Tries fast pymupdf first, falls back to Docling for scanned/complex PDFs."""

        # Tier 1: PyMuPDF (fast, handles 90%+ of PDFs)
        if self._pymupdf:
            try:
                doc = await self._pymupdf.extract(url_or_path, extract_tables=extract_tables)
                logger.info("PDF extracted via PyMuPDF (%d pages)", doc.num_pages or 0)
                return doc
            except APIError as e:
                if "scanned" in str(e).lower() or "image-based" in str(e).lower():
                    logger.info("PDF needs OCR, falling back to Docling: %s", e)
                else:
                    logger.warning("PyMuPDF extraction failed: %s", e)
            except Exception as e:
                logger.warning("PyMuPDF unexpected error, trying Docling: %s", e)

        # Tier 2: Docling Serve (heavy, handles scanned/complex PDFs)
        if self._docling:
            try:
                doc = await self._docling.convert(
                    url_or_path,
                    extract_tables=extract_tables,
                    extract_images=extract_images,
                )
                logger.info("PDF extracted via Docling Serve")
                return doc
            except APIError as e:
                logger.warning("Docling extraction failed: %s", e)

        # No extraction method available or all failed
        methods_tried = []
        if self._pymupdf:
            methods_tried.append("PyMuPDF")
        if self._docling:
            methods_tried.append("Docling Serve")

        if not methods_tried:
            raise ServiceError(
                "No PDF extraction method available. Install pymupdf4llm "
                "(pip install pymupdf4llm) or configure Docling Serve."
            )
        raise ServiceError(f"PDF extraction failed with all methods: {', '.join(methods_tried)}")

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
