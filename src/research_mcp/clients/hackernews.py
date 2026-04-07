"""HackerNews client using the Algolia HN Search API (free, no auth)."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import fetch_json, with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://hn.algolia.com/api/v1"


class HackerNewsClient:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    @with_retry(max_attempts=2)
    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_type: str = "story",
    ) -> list[dict]:
        """Search HN stories and comments via Algolia API."""
        tags = search_type  # "story", "comment", "poll", "show_hn", "ask_hn"

        data = await fetch_json(
            self._client,
            f"{BASE_URL}/search",
            source="hackernews",
            params={
                "query": query,
                "tags": tags,
                "hitsPerPage": min(max_results, 50),
            },
        )

        results = []
        for hit in data.get("hits", []):
            result = {
                "title": hit.get("title", ""),
                "url": hit.get("url"),
                "hn_url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
                "points": hit.get("points", 0),
                "num_comments": hit.get("num_comments", 0),
                "author": hit.get("author", ""),
                "created_at": hit.get("created_at"),
                "story_text": hit.get("story_text", ""),
            }
            results.append(result)

        return results

    @with_retry(max_attempts=2)
    async def get_comments(
        self,
        story_id: str,
        max_comments: int = 10,
    ) -> list[dict]:
        """Get comments for a specific HN story."""
        data = await fetch_json(
            self._client,
            f"{BASE_URL}/items/{story_id}",
            source="hackernews",
        )

        comments = []
        self._collect_comments(data.get("children", []), comments, max_comments)
        return comments

    def _collect_comments(self, children: list[dict], out: list[dict], limit: int, depth: int = 0) -> None:
        """Recursively collect comments, depth-first."""
        for child in children:
            if len(out) >= limit:
                return
            if child.get("text"):
                out.append({
                    "author": child.get("author", ""),
                    "text": child.get("text", ""),
                    "points": child.get("points"),
                    "created_at": child.get("created_at"),
                    "depth": depth,
                })
            self._collect_comments(child.get("children", []), out, limit, depth + 1)
