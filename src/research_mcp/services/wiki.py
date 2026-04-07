"""Wikipedia search and article retrieval service."""

from __future__ import annotations

import httpx

from research_mcp.clients.wikipedia import WikipediaClient
from research_mcp.models.search import SearchResponse


class WikiService:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = WikipediaClient(http_client)

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        return await self._client.search(query, max_results=max_results)

    async def get_article(self, title: str, sections: list[str] | None = None) -> str:
        content = await self._client.get_article(title)

        if sections:
            return self._extract_sections(content, sections)

        return content

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
