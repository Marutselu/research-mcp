"""Forum search service: structured APIs where available, scraping as fallback."""

from __future__ import annotations

import logging
from typing import Any

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

    async def search_forum(
        self,
        query: str,
        site: str,
        max_results: int = 5,
        include_content: bool = True,
    ) -> list[dict[str, Any]]:
        """Search a forum and return full thread content.

        Uses structured APIs for SO/SE/HN, scraping for Reddit and other sites.
        """
        if site in ("stackoverflow", "superuser", "serverfault", "askubuntu",
                     "mathoverflow", "unix", "tex", "dba", "softwareengineering",
                     "codereview", "stackexchange"):
            return await self._search_stackexchange(query, site, max_results, include_content)
        elif site == "hackernews":
            return await self._search_hackernews(query, max_results, include_content)
        elif site == "reddit":
            return await self._search_reddit(query, max_results, include_content)
        else:
            return await self._search_generic(query, site, max_results, include_content)

    async def _search_stackexchange(
        self, query: str, site: str, max_results: int, include_content: bool,
    ) -> list[dict[str, Any]]:
        """Search StackExchange with structured API — questions + top answers."""
        se_site = "stackoverflow" if site == "stackexchange" else site
        questions = await self._stackexchange.search(query, site=se_site, max_results=max_results)

        results = []
        for q in questions:
            thread: dict[str, Any] = {
                "title": q["title"],
                "url": q["url"],
                "source": f"stackexchange:{q['site']}",
                "score": q["score"],
                "tags": q["tags"],
                "answer_count": q["answer_count"],
                "is_answered": q["is_answered"],
            }

            if include_content:
                thread["question_body"] = q["body"]

                # Fetch top answers
                if q["answer_count"] > 0:
                    try:
                        answers = await self._stackexchange.get_answers(
                            q["question_id"], site=q["site"], max_answers=3,
                        )
                        thread["answers"] = answers
                    except (APIError, httpx.HTTPError) as e:
                        logger.warning("Failed to fetch answers for Q%s: %s", q["question_id"], e)
                        thread["answers"] = []
                else:
                    thread["answers"] = []

            results.append(thread)

        return results

    async def _search_hackernews(
        self, query: str, max_results: int, include_content: bool,
    ) -> list[dict[str, Any]]:
        """Search HN via Algolia — stories + top comments."""
        stories = await self._hackernews.search(query, max_results=max_results)

        results = []
        for story in stories:
            thread: dict[str, Any] = {
                "title": story["title"],
                "url": story["hn_url"],
                "external_url": story["url"],
                "source": "hackernews",
                "points": story["points"],
                "num_comments": story["num_comments"],
                "author": story["author"],
            }

            if include_content and story.get("story_text"):
                thread["body"] = story["story_text"]

            # Fetch top comments for high-engagement stories
            if include_content and story["num_comments"] > 0:
                story_id = story["hn_url"].split("id=")[-1] if "id=" in story["hn_url"] else None
                if story_id:
                    try:
                        comments = await self._hackernews.get_comments(story_id, max_comments=5)
                        thread["comments"] = comments
                    except (APIError, httpx.HTTPError) as e:
                        logger.warning("Failed to fetch HN comments for %s: %s", story_id, e)
                        thread["comments"] = []

            results.append(thread)

        return results

    async def _search_reddit(
        self, query: str, max_results: int, include_content: bool,
    ) -> list[dict[str, Any]]:
        """Search Reddit via SearXNG + scrape old.reddit.com for content."""
        from research_mcp.clients.searxng import SearXNGClient
        from research_mcp.clients.scrapling_client import ScraplingClient
        from research_mcp.services.scraper import ScraperService

        searxng = SearXNGClient(self._http, self._config.services.searxng_url)
        raw = await searxng.search(query=f"site:reddit.com {query}", categories=["general"])

        scrapling = ScraplingClient(self._config.scraping)
        scraper = ScraperService(scrapling, self._config.scraping)

        results = []
        for item in raw.get("results", [])[:max_results]:
            url = item.get("url", "")
            thread: dict[str, Any] = {
                "title": item.get("title", ""),
                "url": url,
                "source": "reddit",
                "snippet": item.get("content", ""),
            }

            if include_content and url:
                # Use old.reddit.com for cleaner HTML
                old_url = url.replace("www.reddit.com", "old.reddit.com")
                try:
                    content = await scraper.scrape(
                        url=old_url,
                        tier="basic",
                        extract_markdown=True,
                        css_selector=".expando .md, .comment .md",
                    )
                    if content and len(content.strip()) > 50:
                        thread["content"] = content
                except Exception as e:
                    logger.warning("Failed to scrape Reddit thread %s: %s", url, e)

            results.append(thread)

        return results

    async def _search_generic(
        self, query: str, site: str, max_results: int, include_content: bool,
    ) -> list[dict[str, Any]]:
        """Search any forum via SearXNG + scrape for content."""
        from research_mcp.clients.searxng import SearXNGClient
        from research_mcp.clients.scrapling_client import ScraplingClient
        from research_mcp.services.scraper import ScraperService

        searxng = SearXNGClient(self._http, self._config.services.searxng_url)
        raw = await searxng.search(query=f"site:{site} {query}", categories=["general"])

        results = []
        for item in raw.get("results", [])[:max_results]:
            url = item.get("url", "")
            thread: dict[str, Any] = {
                "title": item.get("title", ""),
                "url": url,
                "source": site,
                "snippet": item.get("content", ""),
            }

            if include_content and url:
                scrapling = ScraplingClient(self._config.scraping)
                scraper = ScraperService(scrapling, self._config.scraping)
                try:
                    content = await scraper.scrape(
                        url=url,
                        tier="auto",
                        extract_markdown=True,
                        css_selector="article, main, .post, .thread, .topic-body, #content",
                    )
                    if content and len(content.strip()) > 50:
                        thread["content"] = content
                    else:
                        content = await scraper.scrape(url=url, tier="auto", extract_markdown=True)
                        thread["content"] = content
                except Exception as e:
                    logger.warning("Failed to scrape %s: %s", url, e)

            results.append(thread)

        return results
