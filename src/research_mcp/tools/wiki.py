"""Wikipedia tools (Group 6: wikipedia)."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from research_mcp.cache import Cache
from research_mcp.models.search import PaginatedContent, SearchResponse
from research_mcp.services.wiki import WikiService


def register_wiki_tools(mcp: FastMCP) -> None:

    @mcp.tool(tags={"wikipedia"})
    async def research_wiki_search(
        query: str,
        max_results: int = 5,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> SearchResponse:
        """Search Wikipedia articles.

        Args:
            query: Search query.
            max_results: Maximum results (1-20).
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: WikiService = ctx.lifespan_context["wiki_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_wiki_search", {"query": query, "max_results": max_results})

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return SearchResponse(**cached)

        result = await service.search(query, max_results=max_results)
        cache.set(cache_key, result.model_dump(), ttl_seconds=config.cache.ttl.search_results, source="wiki_search")
        return result

    @mcp.tool(tags={"wikipedia"})
    async def research_wiki_article(
        title: str,
        sections: list[str] | None = None,
        start_index: int = 0,
        max_length: int = 20000,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> PaginatedContent:
        """Retrieve a Wikipedia article's content as markdown.

        Args:
            title: Article title (e.g., 'Python (programming language)').
            sections: Optional list of section titles to retrieve (returns full article if omitted).
            start_index: Character offset for pagination.
            max_length: Maximum characters to return.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: WikiService = ctx.lifespan_context["wiki_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_wiki_article", {"title": title, "sections": sections})

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return _paginate(cached["content"], start_index, max_length)

        content = await service.get_article(title, sections=sections)
        cache.set(cache_key, {"content": content}, ttl_seconds=config.cache.ttl.web_pages, source="wiki_article")
        return _paginate(content, start_index, max_length)


def _paginate(content: str, start_index: int, max_length: int) -> PaginatedContent:
    total = len(content)
    chunk = content[start_index : start_index + max_length]
    return PaginatedContent(
        content=chunk,
        total_length=total,
        start_index=start_index,
        retrieved_length=len(chunk),
        is_truncated=start_index + len(chunk) < total,
        has_more=start_index + len(chunk) < total,
    )
