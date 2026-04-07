"""GitHub REST API client."""

from __future__ import annotations

import base64
import logging

import httpx

from research_mcp.clients.http import fetch_json, with_retry
from research_mcp.models.search import NormalizedResult, SearchResponse

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"


class GitHubClient:
    def __init__(self, http_client: httpx.AsyncClient, pat: str | None = None) -> None:
        self._client = http_client
        self._pat = pat

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json"}
        if self._pat:
            h["Authorization"] = f"Bearer {self._pat}"
        return h

    @with_retry(max_attempts=3)
    async def search(
        self,
        query: str,
        search_type: str = "repos",
        language: str | None = None,
        max_results: int = 10,
    ) -> SearchResponse:
        q = query
        if language:
            q += f" language:{language}"

        endpoint_map = {
            "repos": "repositories",
            "code": "code",
            "issues": "issues",
            "discussions": "discussions",
        }
        endpoint = endpoint_map.get(search_type, "repositories")

        data = await fetch_json(
            self._client,
            f"{API_BASE}/search/{endpoint}",
            source="github",
            params={"q": q, "per_page": min(max_results, 100), "sort": "best-match"},
            headers=self._headers(),
        )

        results = []
        for item in data.get("items", []):
            results.append(_parse_item(item, search_type))

        return SearchResponse(
            results=results,
            total=data.get("total_count", len(results)),
            query=query,
            has_more=data.get("total_count", 0) > max_results,
        )

    @with_retry(max_attempts=2)
    async def read_file(
        self,
        owner: str,
        repo: str,
        path: str = "README.md",
        ref: str | None = None,
    ) -> str:
        params = {}
        if ref:
            params["ref"] = ref

        data = await fetch_json(
            self._client,
            f"{API_BASE}/repos/{owner}/{repo}/contents/{path}",
            source="github",
            params=params,
            headers=self._headers(),
        )

        if data.get("encoding") == "base64" and data.get("content"):
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return content

        return data.get("content", "")


def _parse_item(item: dict, search_type: str) -> NormalizedResult:
    if search_type == "repos":
        return NormalizedResult(
            title=item.get("full_name", ""),
            url=item.get("html_url"),
            snippet=item.get("description", "") or "",
            source="github",
            content_type="repo",
            date=item.get("updated_at"),
            score=item.get("score"),
            metadata={
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language"),
                "forks": item.get("forks_count", 0),
                "topics": item.get("topics", []),
            },
        )
    elif search_type == "code":
        repo = item.get("repository", {})
        return NormalizedResult(
            title=f"{repo.get('full_name', '')}:{item.get('path', '')}",
            url=item.get("html_url"),
            snippet=item.get("name", ""),
            source="github",
            content_type="code",
            metadata={"repo": repo.get("full_name", ""), "path": item.get("path", "")},
        )
    else:
        # Issues/discussions
        return NormalizedResult(
            title=item.get("title", ""),
            url=item.get("html_url"),
            snippet=item.get("body", "")[:200] if item.get("body") else "",
            source="github",
            content_type="issue" if search_type == "issues" else "discussion",
            date=item.get("created_at"),
            score=item.get("score"),
            metadata={
                "state": item.get("state"),
                "comments": item.get("comments", 0),
                "labels": [l.get("name") for l in item.get("labels", [])],
            },
        )
