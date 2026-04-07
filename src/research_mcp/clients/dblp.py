"""dblp computer science bibliography API client."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import fetch_json, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://dblp.org/search/publ/api"


class DBLPClient:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    @with_retry(max_attempts=3)
    async def search(
        self,
        query: str,
        max_results: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[Paper]:
        params = {
            "q": query,
            "format": "json",
            "h": max_results,
        }

        data = await fetch_json(
            self._client, BASE_URL, source="dblp", params=params
        )

        hits = data.get("result", {}).get("hits", {}).get("hit", [])
        papers = []

        for hit in hits:
            info = hit.get("info", {})
            paper = _parse_hit(info)
            if year_min and paper.year and paper.year < year_min:
                continue
            if year_max and paper.year and paper.year > year_max:
                continue
            papers.append(paper)

        return papers


def _parse_hit(info: dict) -> Paper:
    title = info.get("title", "")
    if title.endswith("."):
        title = title[:-1]

    # Authors can be a single dict or a list
    authors_data = info.get("authors", {}).get("author", [])
    if isinstance(authors_data, dict):
        authors_data = [authors_data]
    authors = []
    for a in authors_data:
        if isinstance(a, dict):
            authors.append(a.get("text", ""))
        elif isinstance(a, str):
            authors.append(a)

    year = None
    if info.get("year"):
        try:
            year = int(info["year"])
        except (ValueError, TypeError):
            pass

    # Extract DOI from electronic edition URL
    doi = None
    ee = info.get("ee")
    if ee:
        if isinstance(ee, list):
            for e in ee:
                url = e if isinstance(e, str) else e.get("text", "")
                if "doi.org/" in url:
                    doi = url.split("doi.org/")[-1]
                    break
        elif isinstance(ee, str) and "doi.org/" in ee:
            doi = ee.split("doi.org/")[-1]

    venue = info.get("venue")

    url = info.get("url")
    if not url and ee:
        url = ee if isinstance(ee, str) else (ee[0] if isinstance(ee, list) else None)
        if isinstance(url, dict):
            url = url.get("text")

    return Paper(
        title=title,
        authors=authors,
        doi=doi,
        year=year,
        venue=venue,
        url=url,
        source="dblp",
        external_ids={"DOI": doi} if doi else {},
    )
