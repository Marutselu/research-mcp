"""Crossref REST API client."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import fetch_json, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.crossref.org"


class CrossrefClient:
    def __init__(self, http_client: httpx.AsyncClient, mailto: str | None = None) -> None:
        self._client = http_client
        self._mailto = mailto

    def _params(self, extra: dict | None = None) -> dict:
        params = {}
        if self._mailto:
            params["mailto"] = self._mailto
        if extra:
            params.update(extra)
        return params

    @with_retry(max_attempts=3)
    async def search(
        self,
        query: str,
        max_results: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[Paper]:
        params = self._params({
            "query": query,
            "rows": max_results,
            "sort": "relevance",
            "order": "desc",
        })

        filters = []
        if year_min:
            filters.append(f"from-pub-date:{year_min}")
        if year_max:
            filters.append(f"until-pub-date:{year_max}")
        if filters:
            params["filter"] = ",".join(filters)

        data = await fetch_json(
            self._client, f"{BASE_URL}/works", source="crossref", params=params
        )

        items = data.get("message", {}).get("items", [])
        return [_parse_work(item) for item in items]

    @with_retry(max_attempts=3)
    async def get_by_doi(self, doi: str) -> Paper:
        data = await fetch_json(
            self._client,
            f"{BASE_URL}/works/{doi}",
            source="crossref",
            params=self._params(),
        )
        return _parse_work(data.get("message", {}))


def _parse_work(item: dict) -> Paper:
    title_list = item.get("title", [])
    title = title_list[0] if title_list else ""

    authors = []
    for a in item.get("author", []):
        given = a.get("given", "")
        family = a.get("family", "")
        name = f"{given} {family}".strip()
        if name:
            authors.append(name)

    # Abstract (may contain JATS XML tags)
    abstract = item.get("abstract")
    if abstract:
        import re
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    # Year from published-print or published-online
    year = None
    for date_field in ("published-print", "published-online", "created"):
        date_parts = item.get(date_field, {}).get("date-parts", [[]])
        if date_parts and date_parts[0]:
            year = date_parts[0][0]
            break

    # PDF URL from links
    pdf_url = None
    for link in item.get("link", []):
        content_type = link.get("content-type", "")
        if "pdf" in content_type:
            pdf_url = link.get("URL")
            break

    doi = item.get("DOI")
    is_oa = item.get("is-referenced-by-count") is not None  # Rough proxy

    venue_list = item.get("container-title", [])
    venue = venue_list[0] if venue_list else None

    return Paper(
        title=title,
        authors=authors,
        abstract=abstract,
        doi=doi,
        year=year,
        venue=venue,
        citation_count=item.get("is-referenced-by-count"),
        url=f"https://doi.org/{doi}" if doi else None,
        pdf_url=pdf_url,
        is_open_access=None,  # Crossref doesn't reliably indicate OA
        source="crossref",
        external_ids={"DOI": doi} if doi else {},
    )
