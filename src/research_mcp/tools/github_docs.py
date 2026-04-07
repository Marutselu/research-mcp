"""GitHub & Docs tools (Group 4: github_docs)."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from research_mcp.cache import Cache
from research_mcp.models.search import SearchResponse
from research_mcp.services.github_docs import GitHubDocsService


def register_github_docs_tools(mcp: FastMCP) -> None:

    @mcp.tool(tags={"github_docs"})
    async def research_github_search(
        query: str,
        search_type: str = "repos",
        language: str | None = None,
        max_results: int = 10,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> SearchResponse:
        """Search GitHub for repositories, code, issues, or discussions.

        Args:
            query: Search query.
            search_type: What to search - 'repos', 'code', 'issues', or 'discussions'.
            language: Filter by programming language (e.g., 'python', 'typescript').
            max_results: Maximum results.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: GitHubDocsService = ctx.lifespan_context["github_docs_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_github_search", {
            "query": query, "type": search_type, "language": language, "max_results": max_results,
        })

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return SearchResponse(**cached)

        result = await service.github_search(query, search_type=search_type, language=language, max_results=max_results)
        cache.set(cache_key, result.model_dump(), ttl_seconds=config.cache.ttl.search_results, source="github_search")
        return result

    @mcp.tool(tags={"github_docs"})
    async def research_github_read_file(
        owner: str,
        repo: str,
        path: str = "README.md",
        ref: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Read a file from a public GitHub repository.

        Args:
            owner: Repository owner (e.g., 'anthropics').
            repo: Repository name (e.g., 'claude-code').
            path: File path within the repo (default: README.md).
            ref: Branch, tag, or commit SHA (default: repo's default branch).
        """
        service: GitHubDocsService = ctx.lifespan_context["github_docs_service"]
        return await service.read_github_file(owner, repo, path=path, ref=ref)

    @mcp.tool(tags={"github_docs"})
    async def research_package_docs(
        package_name: str,
        registry: str = "pypi",
        query: str | None = None,
        max_results: int = 5,
        ctx: Context = None,
    ) -> SearchResponse:
        """Search documentation for a Python or npm package.

        Finds and scrapes relevant doc pages via SearXNG site-restricted search.

        Args:
            package_name: Package name (e.g., 'fastapi', 'react').
            registry: Package registry - 'pypi' or 'npm'.
            query: Optional specific query within the docs.
            max_results: Maximum results.
        """
        service: GitHubDocsService = ctx.lifespan_context["github_docs_service"]
        return await service.search_package_docs(package_name, registry=registry, query=query, max_results=max_results)

    @mcp.tool(tags={"github_docs"})
    async def research_docs_search(
        query: str,
        site: str | None = None,
        max_results: int = 10,
        ctx: Context = None,
    ) -> SearchResponse:
        """Search official documentation sites.

        Args:
            query: Search query.
            site: Optional domain to restrict search to (e.g., 'docs.python.org', 'react.dev').
            max_results: Maximum results.
        """
        service: GitHubDocsService = ctx.lifespan_context["github_docs_service"]
        return await service.search_docs(query, site=site, max_results=max_results)
