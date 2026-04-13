"""Web Search & Scraping tools (Group 1: web_search)."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from typing import Any

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
        max_results: int = 5,
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

        # Cap max_results against config maximum
        effective_max = min(max_results, config.search.max_results)

        cache_key = cache.make_key(
            "research_web_search",
            {
                "query": query,
                "categories": categories,
                "time_range": time_range,
                "max_results": effective_max,
            },
        )

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return SearchResponse(**cached)

        result = await service.search(
            query=query,
            categories=categories or ["general"],
            time_range=time_range,
            max_results=effective_max,
        )

        cache.set(cache_key, result.model_dump(), ttl_seconds=config.cache.ttl.search_results, source="web_search")
        return result

    @mcp.tool(tags={"web_search"})
    async def research_scrape_url(
        url: str,
        tier: str = "auto",
        extract_main_content: bool = False,
        css_selector: str | None = None,
        start_index: int = 0,
        max_length: int = 20000,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> PaginatedContent:
        """Fetch and extract content from any URL as clean markdown. Handles JavaScript-rendered pages and sites that block simple HTTP requests.

        Args:
            url: The URL to scrape.
            tier: Scraping tier - 'basic' (fast HTTP), 'dynamic' (renders JS), 'stealth' (anti-bot bypass), or 'auto' (escalates on failure).
            extract_main_content: If true, extract only the main article body (strips nav, ads, sidebars). Good for news articles and blog posts.
            css_selector: Optional CSS selector to extract specific content (overrides extract_main_content).
            start_index: Character offset for pagination.
            max_length: Maximum characters to return.
            bypass_cache: Skip cache and fetch fresh.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: ScraperService = ctx.lifespan_context["scraper_service"]
        config = ctx.lifespan_context["config"]

        # If extract_main_content, use article-focused CSS selectors
        effective_selector = css_selector
        if extract_main_content and not css_selector:
            effective_selector = "article, main, .post-content, .article-content, .entry-content, #content"

        cache_key = cache.make_key(
            "research_scrape_url",
            {
                "url": url,
                "tier": tier,
                "css_selector": effective_selector,
            },
        )

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                full_content = cached["content"]
                return _paginate(full_content, start_index, max_length)

        full_content = await service.scrape(
            url=url,
            tier=tier,
            extract_markdown=True,
            css_selector=effective_selector,
        )

        # If main content extraction returned too little, retry without selector
        if extract_main_content and not css_selector and len(full_content.strip()) < 100:
            full_content = await service.scrape(url=url, tier=tier, extract_markdown=True)

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
        """Search forum discussions and return a list of threads with metadata for evaluation.

        Returns titles, scores, answer counts, tags, and short previews — NOT full content.
        Use research_forum_thread to read the full content of specific threads you choose.

        Uses StackExchange API for SO/SE (structured metadata with vote scores),
        Algolia API for HackerNews, SearXNG for Reddit and other forums.

        Args:
            query: Search query string.
            site: Forum to search — 'stackoverflow', 'stackexchange' (all SE sites), 'reddit', 'hackernews', or any domain.
            max_results: Maximum threads to list.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        config = ctx.lifespan_context["config"]
        forum_service = ctx.lifespan_context["forum_service"]

        cache_key = cache.make_key(
            "research_forum_search",
            {
                "query": query,
                "site": site,
                "max_results": max_results,
            },
        )

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return SearchResponse(**cached)

        threads = await forum_service.search_forum(
            query=query,
            site=site,
            max_results=max_results,
            include_content=False,
        )

        results = []
        for thread in threads:
            metadata: dict[str, Any] = {}
            if "score" in thread:
                metadata["score"] = thread["score"]
            if "answer_count" in thread:
                metadata["answer_count"] = thread["answer_count"]
            if "is_answered" in thread:
                metadata["is_answered"] = thread["is_answered"]
            if "tags" in thread:
                metadata["tags"] = thread["tags"]
            if "points" in thread:
                metadata["points"] = thread["points"]
            if "num_comments" in thread:
                metadata["num_comments"] = thread["num_comments"]
            if "question_id" in thread:
                metadata["question_id"] = thread["question_id"]

            results.append(
                NormalizedResult(
                    title=thread.get("title", ""),
                    url=thread.get("url", ""),
                    snippet=thread.get("snippet", thread.get("question_body", ""))[:300],
                    source=thread.get("source", site),
                    content_type="forum_thread",
                    metadata=metadata,
                )
            )

        response = SearchResponse(results=results, total=len(results), query=query)
        cache.set(cache_key, response.model_dump(), ttl_seconds=config.cache.ttl.search_results, source="forum_search")
        return response

    @mcp.tool(tags={"web_search"})
    async def research_forum_thread(
        url: str,
        site: str | None = None,
        question_id: int | None = None,
        start_index: int = 0,
        max_length: int = 20000,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> PaginatedContent:
        """Read the full content of a specific forum thread (question + answers/comments).

        Use after research_forum_search to read threads you've chosen.
        For StackOverflow/SE, pass the question_id for structured API access.
        For other sites, pass the URL to scrape.

        Args:
            url: Thread URL (from research_forum_search results).
            site: Forum site hint — 'stackoverflow', 'hackernews', 'reddit', etc. Auto-detected from URL if omitted.
            question_id: StackExchange question ID (from search metadata) for structured API access.
            start_index: Character offset for pagination.
            max_length: Maximum characters to return.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        config = ctx.lifespan_context["config"]
        forum_service = ctx.lifespan_context["forum_service"]

        cache_key = cache.make_key(
            "research_forum_thread",
            {
                "url": url,
                "site": site,
                "question_id": question_id,
            },
        )

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return _paginate(cached["content"], start_index, max_length)

        content = await forum_service.get_thread_content(
            url=url,
            site=site,
            question_id=question_id,
        )

        cache.set(cache_key, {"content": content}, ttl_seconds=config.cache.ttl.web_pages, source="forum_thread")
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
