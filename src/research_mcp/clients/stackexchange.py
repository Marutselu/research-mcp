"""StackExchange API v2.3 client for structured Q&A content."""

from __future__ import annotations

import html
import logging
import re

import httpx

from research_mcp.clients.http import fetch_json, with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://api.stackexchange.com/2.3"

# Map friendly names to SE API site slugs
SITE_MAP = {
    "stackoverflow": "stackoverflow",
    "superuser": "superuser",
    "serverfault": "serverfault",
    "askubuntu": "askubuntu",
    "mathoverflow": "mathoverflow.net",
    "unix": "unix",
    "tex": "tex",
    "dba": "dba",
    "softwareengineering": "softwareengineering",
    "codereview": "codereview",
}


def _decode_html(text: str) -> str:
    """Decode HTML entities and strip tags."""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


class StackExchangeClient:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    @with_retry(max_attempts=2)
    async def search(
        self,
        query: str,
        site: str = "stackoverflow",
        max_results: int = 5,
        sort: str = "relevance",
    ) -> list[dict]:
        """Search for questions and return structured results with answers."""
        se_site = SITE_MAP.get(site, site)

        data = await fetch_json(
            self._client,
            f"{BASE_URL}/search/advanced",
            source="stackexchange",
            params={
                "q": query,
                "site": se_site,
                "pagesize": min(max_results, 25),
                "sort": sort,
                "order": "desc",
                "filter": "withbody",  # Include question body
                "accepted": "True",  # Prefer questions with accepted answers
            },
        )

        questions = []
        for item in data.get("items", []):
            questions.append({
                "question_id": item.get("question_id"),
                "title": _decode_html(item.get("title", "")),
                "body": _decode_html(item.get("body", "")),
                "url": item.get("link"),
                "score": item.get("score", 0),
                "answer_count": item.get("answer_count", 0),
                "is_answered": item.get("is_answered", False),
                "accepted_answer_id": item.get("accepted_answer_id"),
                "tags": item.get("tags", []),
                "creation_date": item.get("creation_date"),
                "site": se_site,
            })

        return questions

    @with_retry(max_attempts=2)
    async def get_answers(
        self,
        question_id: int,
        site: str = "stackoverflow",
        max_answers: int = 3,
    ) -> list[dict]:
        """Get answers for a specific question, sorted by votes."""
        se_site = SITE_MAP.get(site, site)

        data = await fetch_json(
            self._client,
            f"{BASE_URL}/questions/{question_id}/answers",
            source="stackexchange",
            params={
                "site": se_site,
                "pagesize": min(max_answers, 10),
                "sort": "votes",
                "order": "desc",
                "filter": "withbody",
            },
        )

        answers = []
        for item in data.get("items", []):
            answers.append({
                "answer_id": item.get("answer_id"),
                "body": _decode_html(item.get("body", "")),
                "score": item.get("score", 0),
                "is_accepted": item.get("is_accepted", False),
                "creation_date": item.get("creation_date"),
            })

        return answers
