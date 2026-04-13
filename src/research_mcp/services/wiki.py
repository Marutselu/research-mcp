"""Wikipedia and Wikidata search and retrieval service."""

from __future__ import annotations

from typing import Any

import httpx

from research_mcp.clients.wikidata_client import WikidataClient
from research_mcp.clients.wikipedia import WikipediaClient
from research_mcp.models.search import SearchResponse


class WikiService:
    """Service for Wikipedia articles and Wikidata entities."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._wikipedia = WikipediaClient(http_client)
        self._wikidata = WikidataClient(http_client)

    # --- Wikipedia methods ---

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        """Search Wikipedia articles."""
        return await self._wikipedia.search(query, max_results=max_results)

    async def get_article(self, title: str, sections: list[str] | None = None) -> str:
        """Get Wikipedia article content."""
        content = await self._wikipedia.get_article(title)

        if sections:
            return self._extract_sections(content, sections)

        return content

    # --- Wikidata methods ---

    async def search_wikidata(self, query: str, max_results: int = 10, language: str = "en") -> SearchResponse:
        """Search Wikidata entities.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            language: Language code for labels and descriptions.

        Returns:
            SearchResponse with normalized results.
        """
        return await self._wikidata.search(query, max_results=max_results, language=language)

    async def get_entity(self, entity_id: str, language: str = "en") -> dict[str, Any]:
        """Fetch detailed information about a Wikidata entity.

        Args:
            entity_id: Wikidata entity ID (e.g., 'Q42' for Douglas Adams).
            language: Language code for labels and descriptions.

        Returns:
            Dictionary with entity data including labels, descriptions, claims, etc.
        """
        return await self._wikidata.get_entity(entity_id, language=language)

    # --- Private helpers ---

    def _extract_sections(self, content: str, sections: list[str]) -> str:
        """Extract specific sections from markdown content, including subsections."""
        lines = content.split("\n")
        result_lines = []
        capturing = False
        capture_level = 0

        target_sections = {s.lower() for s in sections}

        for line in lines:
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                heading = line.lstrip("#").strip().lower()
                if heading in target_sections:
                    capturing = True
                    capture_level = level
                    result_lines.append(line)
                elif capturing and level <= capture_level:
                    # Same or higher-level heading = end of section
                    capturing = False
                elif capturing:
                    # Sub-heading within the section
                    result_lines.append(line)
            elif capturing:
                result_lines.append(line)

        return "\n".join(result_lines) if result_lines else content
