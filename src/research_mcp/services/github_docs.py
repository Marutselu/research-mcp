"""GitHub & docs search service."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.github import GitHubClient
from research_mcp.clients.searxng import SearXNGClient
from research_mcp.config import ResearchMCPConfig
from research_mcp.models.search import NormalizedResult, SearchResponse

logger = logging.getLogger(__name__)


class GitHubDocsService:
    def __init__(self, http_client: httpx.AsyncClient, config: ResearchMCPConfig) -> None:
        self._github = GitHubClient(http_client, config.github_pat)
        # SearXNG client for docs/package search
        self._searxng = SearXNGClient(http_client, config.services.searxng_url)

    async def github_search(
        self,
        query: str,
        search_type: str = "repos",
        language: str | None = None,
        max_results: int = 10,
    ) -> SearchResponse:
        return await self._github.search(query, search_type=search_type, language=language, max_results=max_results)

    async def read_github_file(
        self,
        owner: str,
        repo: str,
        path: str = "README.md",
        ref: str | None = None,
    ) -> str:
        return await self._github.read_file(owner, repo, path=path, ref=ref)

    async def search_package_docs(
        self,
        package_name: str,
        registry: str = "pypi",
        query: str | None = None,
        max_results: int = 5,
    ) -> SearchResponse:
        """Search package documentation via SearXNG site-restricted search."""
        doc_sites = {
            "pypi": [
                f"site:readthedocs.io {package_name}",
                f"site:pypi.org {package_name}",
            ],
            "npm": [
                f"site:npmjs.com {package_name}",
                f"site:github.com {package_name}",
            ],
        }

        sites = doc_sites.get(registry, [f"site:github.com {package_name}"])
        search_query = f"{' OR '.join(sites)}"
        if query:
            search_query = f"{package_name} {query} ({' OR '.join(sites)})"

        raw = await self._searxng.search(query=search_query, categories=["general"])

        results = []
        for item in raw.get("results", []):
            results.append(
                NormalizedResult(
                    title=item.get("title", ""),
                    url=item.get("url"),
                    snippet=item.get("content", ""),
                    source="docs",
                    content_type="documentation",
                    metadata={"package": package_name, "registry": registry},
                )
            )
            if len(results) >= max_results:
                break

        return SearchResponse(results=results, total=len(results), query=f"{package_name} docs")

    async def search_docs(
        self,
        query: str,
        site: str | None = None,
        max_results: int = 10,
    ) -> SearchResponse:
        """Search official documentation sites."""
        search_query = query
        if site:
            search_query = f"site:{site} {query}"

        raw = await self._searxng.search(query=search_query, categories=["general"])

        results = []
        for item in raw.get("results", []):
            results.append(
                NormalizedResult(
                    title=item.get("title", ""),
                    url=item.get("url"),
                    snippet=item.get("content", ""),
                    source="docs",
                    content_type="documentation",
                    date=item.get("publishedDate"),
                )
            )
            if len(results) >= max_results:
                break

        return SearchResponse(results=results, total=len(results), query=query)
