"""Web Search & Scraping tools (Group 1: web_search)."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from research_mcp.cache import Cache
from research_mcp.models.search import NormalizedResult, PaginatedContent, SearchResponse
from research_mcp.services.scraper import ScraperService
from research_mcp.services.web_search import WebSearchService


def register_web_tools(mcp: FastMCP) -> None:

    @mcp.tool(tags={"web_search"})
    async def research_web_search(
        query: str,
        categories: list[str] | None = None,
        time_range: str | None = None,
        max_results: int = 10,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> SearchResponse:
        """Search the web using SearXNG meta-search engine.

        Args:
            query: Search query string.
            categories: Search categories (general, news, science, files, images, videos, music, social_media, it).
            time_range: Time filter (day, week, month, year).
            max_results: Maximum number of results to return.
            bypass_cache: Skip cache and fetch fresh results.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: WebSearchService = ctx.lifespan_context["web_search_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_web_search", {
            "query": query, "categories": categories, "time_range": time_range, "max_results": max_results,
        })

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return SearchResponse(**cached)

        result = await service.search(
            query=query,
            categories=categories or ["general"],
            time_range=time_range,
            max_results=max_results,
        )

        cache.set(cache_key, result.model_dump(), ttl_seconds=config.cache.ttl.search_results, source="web_search")
        return result

    @mcp.tool(tags={"web_search"})
    async def research_scrape_url(
        url: str,
        tier: str = "auto",
        extract_markdown: bool = True,
        css_selector: str | None = None,
        start_index: int = 0,
        max_length: int = 20000,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> PaginatedContent:
        """Fetch and extract content from a URL with anti-bot scraping capabilities.

        Args:
            url: The URL to scrape.
            tier: Scraping tier - 'basic' (fast HTTP), 'dynamic' (renders JS), 'stealth' (anti-bot bypass), or 'auto' (escalates on failure).
            extract_markdown: Convert HTML to clean markdown.
            css_selector: Optional CSS selector to extract specific content.
            start_index: Character offset for pagination.
            max_length: Maximum characters to return (for pagination).
            bypass_cache: Skip cache and fetch fresh.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: ScraperService = ctx.lifespan_context["scraper_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_scrape_url", {
            "url": url, "tier": tier, "css_selector": css_selector,
        })

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                full_content = cached["content"]
                return _paginate(full_content, start_index, max_length)

        full_content = await service.scrape(
            url=url,
            tier=tier,
            extract_markdown=extract_markdown,
            css_selector=css_selector,
        )

        cache.set(cache_key, {"content": full_content}, ttl_seconds=config.cache.ttl.web_pages, source="scrape_url")
        return _paginate(full_content, start_index, max_length)

    @mcp.tool(tags={"web_search"})
    async def research_forum_search(
        query: str,
        site: str,
        max_results: int = 10,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> SearchResponse:
        """Search forum discussions on Reddit, StackOverflow, StackExchange, or HackerNews.

        Uses SearXNG with site-restricted queries for targeted forum search.

        Args:
            query: Search query string.
            site: Forum to search - 'reddit', 'stackoverflow', 'stackexchange', or 'hackernews'.
            max_results: Maximum number of results.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: WebSearchService = ctx.lifespan_context["web_search_service"]
        config = ctx.lifespan_context["config"]

        site_domains = {
            "reddit": "reddit.com",
            "stackoverflow": "stackoverflow.com",
            "stackexchange": "stackexchange.com",
            "hackernews": "news.ycombinator.com",
        }
        domain = site_domains.get(site, site)
        site_query = f"site:{domain} {query}"

        cache_key = cache.make_key("research_forum_search", {
            "query": query, "site": site, "max_results": max_results,
        })

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return SearchResponse(**cached)

        result = await service.search(
            query=site_query,
            categories=["general"],
            max_results=max_results,
        )
        # Override query to show original, not the site: prefixed one
        result.query = query

        cache.set(cache_key, result.model_dump(), ttl_seconds=config.cache.ttl.search_results, source="forum_search")
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
