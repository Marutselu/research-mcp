"""DOAJ (Directory of Open Access Journals) API client."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import fetch_json, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://doaj.org/api/search/articles"


class DOAJClient:
    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self._client = http_client
        self._api_key = api_key

    @with_retry(max_attempts=3)
    async def search(
        self,
        query: str,
        max_results: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[Paper]:
        params: dict = {"pageSize": max_results}
        if self._api_key:
            params["api_key"] = self._api_key

        search_url = f"{BASE_URL}/{query}"

        data = await fetch_json(
            self._client, search_url, source="doaj", params=params
        )

        papers = []
        for item in data.get("results", []):
            paper = _parse_article(item)
            if year_min and paper.year and paper.year < year_min:
                continue
            if year_max and paper.year and paper.year > year_max:
                continue
            papers.append(paper)

        return papers


def _parse_article(item: dict) -> Paper:
    bibjson = item.get("bibjson", {})

    title = bibjson.get("title", "")

    authors = []
    for a in bibjson.get("author", []):
        name = a.get("name", "")
        if name:
            authors.append(name)

    abstract = bibjson.get("abstract")

    # Identifiers
    doi = None
    for ident in bibjson.get("identifier", []):
        if ident.get("type") == "doi":
            doi = ident.get("id")
            break

    # Year
    year = None
    if bibjson.get("year"):
        try:
            year = int(bibjson["year"])
        except (ValueError, TypeError):
            pass

    # Journal
    journal = bibjson.get("journal", {})
    venue = journal.get("title")

    # URLs
    pdf_url = None
    url = None
    for link in bibjson.get("link", []):
        link_type = link.get("type", "")
        if "fulltext" in link_type.lower():
            url = link.get("url")
            if link.get("content_type") == "application/pdf":
                pdf_url = link.get("url")

    return Paper(
        title=title,
        authors=authors,
        abstract=abstract,
        doi=doi,
        year=year,
        venue=venue,
        url=url or (f"https://doi.org/{doi}" if doi else None),
        pdf_url=pdf_url,
        is_open_access=True,  # All DOAJ content is OA
        source="doaj",
        external_ids={"DOI": doi} if doi else {},
    )
