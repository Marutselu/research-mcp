"""Lightweight PDF text extraction using PyMuPDF (pymupdf4llm)."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

import httpx

from research_mcp.clients.http import APIError
from research_mcp.models.document import ExtractedDocument, ExtractedTable

logger = logging.getLogger(__name__)

# Minimum text density to consider a page as having a real text layer.
# Scanned PDFs produce very little text (OCR artifacts, page numbers).
_MIN_CHARS_PER_PAGE = 50


def is_available() -> bool:
    try:
        import pymupdf4llm  # noqa: F401
        return True
    except ImportError:
        return False


class PyMuPDFClient:
    """Fast PDF extraction using PyMuPDF. Handles text-layer PDFs (90%+ of academic papers)."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    async def extract(
        self,
        url_or_path: str,
        extract_tables: bool = True,
    ) -> ExtractedDocument:
        """Extract text from a PDF. Returns ExtractedDocument or raises if no text layer."""
        pdf_path = await self._resolve_to_file(url_or_path)

        try:
            result = await asyncio.to_thread(self._extract_sync, pdf_path, extract_tables)
        finally:
            # Clean up temp file if we downloaded it
            if pdf_path != url_or_path:
                try:
                    Path(pdf_path).unlink(missing_ok=True)
                except OSError:
                    pass

        return result

    async def _resolve_to_file(self, url_or_path: str) -> str:
        """If URL, download to temp file. If path, return as-is."""
        if not url_or_path.startswith(("http://", "https://")):
            return url_or_path

        response = await self._client.get(url_or_path, timeout=60.0, follow_redirects=True)
        if not response.is_success:
            raise APIError(f"Failed to download PDF (HTTP {response.status_code})", source="pymupdf")

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(response.content)
        tmp.close()
        return tmp.name

    def _extract_sync(self, pdf_path: str, extract_tables: bool) -> ExtractedDocument:
        """Synchronous extraction using pymupdf4llm."""
        import pymupdf
        import pymupdf4llm

        doc = pymupdf.open(pdf_path)
        num_pages = len(doc)

        # Check if PDF has a real text layer
        total_chars = sum(len(page.get_text()) for page in doc)
        chars_per_page = total_chars / max(num_pages, 1)

        if chars_per_page < _MIN_CHARS_PER_PAGE:
            doc.close()
            raise APIError(
                f"PDF appears to be scanned/image-based ({chars_per_page:.0f} chars/page). "
                "Docling Serve with OCR is needed for this document.",
                source="pymupdf",
            )

        # Extract as markdown
        md_text = pymupdf4llm.to_markdown(pdf_path)

        # Extract title from first page metadata or first heading
        title = doc.metadata.get("title") if doc.metadata else None
        doc.close()

        # Extract tables if requested
        tables = []
        if extract_tables:
            tables = self._extract_tables(pdf_path)

        return ExtractedDocument(
            content=md_text,
            tables=tables,
            title=title or None,
            num_pages=num_pages,
            source_url=pdf_path,
        )

    def _extract_tables(self, pdf_path: str) -> list[ExtractedTable]:
        """Extract tables using pymupdf's built-in table detection."""
        import pymupdf

        tables = []
        try:
            doc = pymupdf.open(pdf_path)
            for page_num, page in enumerate(doc):
                page_tables = page.find_tables()
                for tab in page_tables:
                    extracted = tab.extract()
                    if not extracted or len(extracted) < 2:
                        continue

                    headers = [str(cell) if cell else "" for cell in extracted[0]]
                    rows = [
                        [str(cell) if cell else "" for cell in row]
                        for row in extracted[1:]
                    ]
                    tables.append(
                        ExtractedTable(
                            headers=headers,
                            rows=rows,
                            page=page_num + 1,
                        )
                    )
            doc.close()
        except Exception as e:
            logger.debug("Table extraction failed: %s", e)

        return tables
