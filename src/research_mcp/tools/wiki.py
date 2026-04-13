"""Wikipedia and Wikidata tools (Group 6: wikipedia)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from research_mcp.cache import Cache
from research_mcp.models.search import PaginatedContent, SearchResponse
from research_mcp.services.wiki import WikiService


def register_wiki_tools(mcp: FastMCP) -> None:

    # --- Wikipedia tools ---

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

    # --- Wikidata tools ---

    @mcp.tool(tags={"wikipedia"})
    async def research_wikidata_search(
        query: str,
        max_results: int = 10,
        language: str = "en",
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> SearchResponse:
        """Search Wikidata entities (knowledge graph).

        Wikidata is a free knowledge base with structured data about entities
        like people, places, organizations, concepts, etc.

        Args:
            query: Search query (e.g., 'Albert Einstein', 'Python programming').
            max_results: Maximum results (1-50).
            language: Language code for labels (e.g., 'en', 'de', 'fr').
            bypass_cache: Skip cache.

        Returns:
            SearchResponse with entity results including ID, label, and description.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: WikiService = ctx.lifespan_context["wiki_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key(
            "research_wikidata_search",
            {"query": query, "max_results": max_results, "language": language},
        )

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return SearchResponse(**cached)

        result = await service.search_wikidata(query, max_results=max_results, language=language)
        cache.set(
            cache_key,
            result.model_dump(),
            ttl_seconds=config.cache.ttl.search_results,
            source="wikidata_search",
        )
        return result

    @mcp.tool(tags={"wikipedia"})
    async def research_wikidata_entity(
        entity_id: str,
        language: str = "en",
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """Fetch detailed information about a Wikidata entity.

        Retrieve structured data about an entity including labels, descriptions,
        aliases, claims (properties), and sitelinks to Wikipedia articles.

        Args:
            entity_id: Wikidata entity ID (e.g., 'Q42' for Douglas Adams, 'Q7251' for Python).
            language: Language code for labels and descriptions.
            bypass_cache: Skip cache.

        Returns:
            Dictionary with:
            - id: Entity ID
            - label: Entity name
            - description: Short description
            - aliases: Alternative names
            - claims: Property-value pairs (e.g., P31=instance of)
            - sitelinks: Links to Wikipedia articles in various languages
            - wikipedia_url: Link to the primary Wikipedia article
            - wikidata_url: Link to the Wikidata page
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: WikiService = ctx.lifespan_context["wiki_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_wikidata_entity", {"entity_id": entity_id, "language": language})

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return cached

        result = await service.get_entity(entity_id, language=language)
        cache.set(
            cache_key,
            result,
            ttl_seconds=config.cache.ttl.web_pages,
            source="wikidata_entity",
        )
        return result


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
