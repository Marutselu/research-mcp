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

        cache_key = cache.make_key("research_scrape_url", {
            "url": url, "tier": tier, "css_selector": effective_selector,
        })

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
        max_results: int = 5,
        include_content: bool = True,
        start_index: int = 0,
        max_length: int = 20000,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> PaginatedContent:
        """Search forum discussions and retrieve full thread content (questions, answers, comments).

        Uses structured APIs for StackOverflow/StackExchange (with vote scores and accepted answers)
        and HackerNews (via Algolia). For Reddit and other forums, searches via SearXNG and scrapes
        full thread content.

        Args:
            query: Search query string.
            site: Forum to search — 'stackoverflow', 'stackexchange' (all SE sites), 'reddit', 'hackernews', or any domain.
            max_results: Maximum threads to retrieve (default 5, since full content is fetched).
            include_content: Fetch full thread content (questions + answers/comments). Set false for links only.
            start_index: Character offset for pagination.
            max_length: Maximum characters to return.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        config = ctx.lifespan_context["config"]
        forum_service = ctx.lifespan_context["forum_service"]

        cache_key = cache.make_key("research_forum_search", {
            "query": query, "site": site, "max_results": max_results, "include_content": include_content,
        })

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return _paginate(cached["content"], start_index, max_length)

        threads = await forum_service.search_forum(
            query=query,
            site=site,
            max_results=max_results,
            include_content=include_content,
        )

        # Format threads into readable markdown
        full_text = _format_threads(threads, site)

        cache.set(cache_key, {"content": full_text}, ttl_seconds=config.cache.ttl.web_pages, source="forum_search")
        return _paginate(full_text, start_index, max_length)


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


def _format_threads(threads: list[dict[str, Any]], site: str) -> str:
    """Format forum threads into readable markdown."""
    parts = []

    for i, thread in enumerate(threads, 1):
        title = thread.get("title", "Untitled")
        url = thread.get("url", "")
        source = thread.get("source", site)

        parts.append(f"## {i}. {title}")
        parts.append(f"**Source:** {source} | **URL:** {url}")

        # StackExchange format
        if "question_body" in thread:
            score = thread.get("score", 0)
            tags = ", ".join(thread.get("tags", []))
            parts.append(f"**Score:** {score} | **Tags:** {tags}")
            parts.append(f"\n### Question\n{thread['question_body']}")

            for j, answer in enumerate(thread.get("answers", []), 1):
                accepted = " (Accepted)" if answer.get("is_accepted") else ""
                parts.append(f"\n### Answer {j}{accepted} (Score: {answer.get('score', 0)})")
                parts.append(answer.get("body", ""))

        # HackerNews format
        elif "comments" in thread:
            points = thread.get("points", 0)
            parts.append(f"**Points:** {points} | **Comments:** {thread.get('num_comments', 0)}")
            if thread.get("external_url"):
                parts.append(f"**Link:** {thread['external_url']}")
            if thread.get("body"):
                parts.append(f"\n{thread['body']}")

            for comment in thread.get("comments", []):
                indent = "  " * comment.get("depth", 0)
                author = comment.get("author", "anon")
                parts.append(f"\n{indent}**{author}:** {comment.get('text', '')}")

        # Reddit / generic scraped format
        elif "content" in thread:
            parts.append(f"\n{thread['content']}")
        elif "snippet" in thread:
            parts.append(f"\n{thread['snippet']}")

        parts.append("\n---\n")

    return "\n".join(parts)
