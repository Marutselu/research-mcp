"""Docling Serve HTTP client for document extraction."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import APIError, raise_for_status
from research_mcp.models.document import ExtractedDocument, ExtractedTable

logger = logging.getLogger(__name__)


class DoclingClient:
    def __init__(self, http_client: httpx.AsyncClient, base_url: str) -> None:
        self._client = http_client
        self._base_url = base_url.rstrip("/")

    async def convert(
        self,
        url_or_path: str,
        extract_tables: bool = True,
        extract_images: bool = False,
    ) -> ExtractedDocument:
        """Send a document to Docling Serve for extraction."""
        try:
            # Determine if it's a URL or file path
            if url_or_path.startswith(("http://", "https://")):
                response = await self._client.post(
                    f"{self._base_url}/v1alpha/convert/source",
                    json={
                        "http_source": {"url": url_or_path},
                        "options": {
                            "to_markdown": True,
                            "include_images": extract_images,
                        },
                    },
                    timeout=120.0,
                )
            else:
                # File upload
                with open(url_or_path, "rb") as f:
                    response = await self._client.post(
                        f"{self._base_url}/v1alpha/convert/file",
                        files={"file": (url_or_path.split("/")[-1], f)},
                        timeout=120.0,
                    )

            raise_for_status(response, source="docling")
            data = response.json()

            return self._parse_response(data, url_or_path)

        except httpx.ConnectError:
            raise APIError(
                f"Cannot connect to Docling Serve at {self._base_url}. Is it running?",
                source="docling",
            )

    def _parse_response(self, data: dict, source_url: str) -> ExtractedDocument:
        """Parse Docling Serve response into ExtractedDocument."""
        # Docling returns markdown content directly
        content = data.get("markdown", data.get("content", ""))

        tables = []
        for table_data in data.get("tables", []):
            tables.append(
                ExtractedTable(
                    caption=table_data.get("caption"),
                    headers=table_data.get("headers", []),
                    rows=table_data.get("rows", []),
                    page=table_data.get("page"),
                )
            )

        figures = [fig.get("caption", "") for fig in data.get("figures", [])]

        return ExtractedDocument(
            content=content,
            tables=tables,
            figures=figures,
            title=data.get("title"),
            num_pages=data.get("num_pages"),
            source_url=source_url,
        )
