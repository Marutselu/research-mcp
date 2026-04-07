"""Forum search service: structured APIs where available, scraping as fallback.

Two-step design:
1. search_forum() — returns thread metadata (titles, scores, tags). Fast, no scraping.
2. get_thread_content() — fetches full content for a specific thread the LLM chose.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from research_mcp.clients.hackernews import HackerNewsClient
from research_mcp.clients.http import APIError
from research_mcp.clients.stackexchange import StackExchangeClient
from research_mcp.config import ResearchMCPConfig

logger = logging.getLogger(__name__)


class ForumSearchService:
    def __init__(self, http_client: httpx.AsyncClient, config: ResearchMCPConfig) -> None:
        self._http = http_client
        self._config = config
        self._stackexchange = StackExchangeClient(http_client)
        self._hackernews = HackerNewsClient(http_client)

    # --- Step 1: Search (metadata only, fast) ---

    async def search_forum(
        self,
        query: str,
        site: str,
        max_results: int = 10,
        include_content: bool = False,
    ) -> list[dict[str, Any]]:
        """Search a forum and return thread metadata for LLM evaluation."""
        if site in ("stackoverflow", "superuser", "serverfault", "askubuntu",
                     "mathoverflow", "unix", "tex", "dba", "softwareengineering",
                     "codereview", "stackexchange"):
            return await self._search_stackexchange(query, site, max_results)
        elif site == "hackernews":
            return await self._search_hackernews(query, max_results)
        elif site == "reddit":
            return await self._search_reddit(query, max_results)
        else:
            return await self._search_generic(query, site, max_results)

    # --- Step 2: Read thread (full content, LLM-selected) ---

    async def get_thread_content(
        self,
        url: str,
        site: str | None = None,
        question_id: int | None = None,
    ) -> str:
        """Fetch full content for a specific thread chosen by the LLM."""
        # Auto-detect site from URL if not provided
        if not site:
            site = self._detect_site(url)

        if site and "stackexchange" in site or site in (
            "stackoverflow", "superuser", "serverfault", "askubuntu", "mathoverflow",
        ):
            return await self._read_stackexchange_thread(url, site, question_id)
        elif site == "hackernews":
            return await self._read_hackernews_thread(url)
        elif site == "reddit":
            return await self._read_reddit_thread(url)
        else:
            return await self._read_generic_thread(url)

    # --- SE search + read ---

    async def _search_stackexchange(
        self, query: str, site: str, max_results: int,
    ) -> list[dict[str, Any]]:
        se_site = "stackoverflow" if site == "stackexchange" else site
        questions = await self._stackexchange.search(query, site=se_site, max_results=max_results)

        results = []
        for q in questions:
            results.append({
                "title": q["title"],
                "url": q["url"],
                "source": f"stackexchange:{q['site']}",
                "snippet": q["body"][:300] if q.get("body") else "",
                "score": q["score"],
                "tags": q["tags"],
                "answer_count": q["answer_count"],
                "is_answered": q["is_answered"],
                "question_id": q["question_id"],
            })
        return results

    async def _read_stackexchange_thread(
        self, url: str, site: str, question_id: int | None,
    ) -> str:
        """Read full SE question + top answers via API."""
        se_site = site.split(":")[-1] if ":" in site else site
        if se_site == "stackexchange":
            se_site = "stackoverflow"

        # Extract question_id from URL if not provided
        if not question_id:
            match = re.search(r"/questions/(\d+)", url)
            if match:
                question_id = int(match.group(1))

        if not question_id:
            return await self._read_generic_thread(url)

        # Get the question body
        questions = await self._stackexchange.search("", site=se_site, max_results=1)
        # Actually we need to fetch the specific question — use search with question ID
        # The SE API doesn't have a direct "get question by ID" in our client, so
        # we'll fetch answers (which is what we really want) and format them

        parts = [f"# Thread: {url}\n"]

        try:
            answers = await self._stackexchange.get_answers(question_id, site=se_site, max_answers=5)
            for i, answer in enumerate(answers, 1):
                accepted = " [ACCEPTED]" if answer.get("is_accepted") else ""
                parts.append(f"\n## Answer {i}{accepted} (Score: {answer.get('score', 0)})\n")
                parts.append(answer.get("body", ""))
        except (APIError, httpx.HTTPError) as e:
            logger.warning("Failed to fetch SE answers for Q%s: %s", question_id, e)
            return await self._read_generic_thread(url)

        return "\n".join(parts)

    # --- HN search + read ---

    async def _search_hackernews(self, query: str, max_results: int) -> list[dict[str, Any]]:
        stories = await self._hackernews.search(query, max_results=max_results)

        results = []
        for story in stories:
            results.append({
                "title": story["title"],
                "url": story["hn_url"],
                "external_url": story.get("url"),
                "source": "hackernews",
                "snippet": story.get("story_text", "")[:300],
                "points": story["points"],
                "num_comments": story["num_comments"],
            })
        return results

    async def _read_hackernews_thread(self, url: str) -> str:
        """Read full HN story + comments."""
        story_id = url.split("id=")[-1] if "id=" in url else None
        if not story_id:
            return await self._read_generic_thread(url)

        parts = [f"# HackerNews Thread\n"]

        try:
            comments = await self._hackernews.get_comments(story_id, max_comments=15)
            for comment in comments:
                indent = "  " * comment.get("depth", 0)
                author = comment.get("author", "anon")
                text = comment.get("text", "")
                parts.append(f"\n{indent}**{author}:**\n{indent}{text}")
        except (APIError, httpx.HTTPError) as e:
            logger.warning("Failed to fetch HN comments for %s: %s", story_id, e)
            return await self._read_generic_thread(url)

        return "\n".join(parts)

    # --- Reddit search + read ---

    async def _search_reddit(self, query: str, max_results: int) -> list[dict[str, Any]]:
        from research_mcp.clients.searxng import SearXNGClient

        searxng = SearXNGClient(self._http, self._config.services.searxng_url)
        raw = await searxng.search(query=f"site:reddit.com {query}", categories=["general"])

        results = []
        for item in raw.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "source": "reddit",
                "snippet": item.get("content", ""),
            })
        return results

    async def _read_reddit_thread(self, url: str) -> str:
        """Scrape full Reddit thread via old.reddit.com."""
        from research_mcp.clients.scrapling_client import ScraplingClient
        from research_mcp.services.scraper import ScraperService

        old_url = url.replace("www.reddit.com", "old.reddit.com")
        scrapling = ScraplingClient(self._config.scraping)
        scraper = ScraperService(scrapling, self._config.scraping)

        content = await scraper.scrape(
            url=old_url,
            tier="basic",
            extract_markdown=True,
            css_selector=".expando .md, .comment .md",
        )
        if content and len(content.strip()) > 50:
            return content

        # Fallback: full page
        return await scraper.scrape(url=old_url, tier="auto", extract_markdown=True)

    # --- Generic search + read ---

    async def _search_generic(self, query: str, site: str, max_results: int) -> list[dict[str, Any]]:
        from research_mcp.clients.searxng import SearXNGClient

        searxng = SearXNGClient(self._http, self._config.services.searxng_url)
        raw = await searxng.search(query=f"site:{site} {query}", categories=["general"])

        results = []
        for item in raw.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "source": site,
                "snippet": item.get("content", ""),
            })
        return results

    async def _read_generic_thread(self, url: str) -> str:
        """Scrape any forum thread via Scrapling."""
        from research_mcp.clients.scrapling_client import ScraplingClient
        from research_mcp.services.scraper import ScraperService

        scrapling = ScraplingClient(self._config.scraping)
        scraper = ScraperService(scrapling, self._config.scraping)

        content = await scraper.scrape(
            url=url,
            tier="auto",
            extract_markdown=True,
            css_selector="article, main, .post, .thread, .topic-body, .comment, #content",
        )
        if content and len(content.strip()) > 50:
            return content

        return await scraper.scrape(url=url, tier="auto", extract_markdown=True)

    # --- Helpers ---

    @staticmethod
    def _detect_site(url: str) -> str | None:
        """Auto-detect forum site from URL."""
        domain = urlparse(url).netloc.lower()
        if "stackoverflow.com" in domain:
            return "stackoverflow"
        if "stackexchange.com" in domain or domain in ("superuser.com", "serverfault.com", "askubuntu.com"):
            return "stackexchange"
        if "news.ycombinator.com" in domain:
            return "hackernews"
        if "reddit.com" in domain:
            return "reddit"
        return None
