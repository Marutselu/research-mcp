"""CORE API v3 client."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import AuthenticationError, fetch_json, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.core.ac.uk/v3"


class CoreClient:
    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self._client = http_client
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    @with_retry(max_attempts=3)
    async def search(
        self,
        query: str,
        max_results: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[Paper]:
        params: dict = {
            "q": query,
            "limit": max_results,
        }

        try:
            data = await fetch_json(
                self._client,
                f"{BASE_URL}/search/works",
                source="core",
                params=params,
                headers=self._headers(),
            )
        except AuthenticationError:
            if self._api_key:
                logger.warning("CORE API key rejected, retrying without key")
                self._api_key = None
                data = await fetch_json(
                    self._client,
                    f"{BASE_URL}/search/works",
                    source="core",
                    params=params,
                )
            else:
                raise

        papers = []
        for item in data.get("results", []):
            paper = _parse_work(item)
            if year_min and paper.year and paper.year < year_min:
                continue
            if year_max and paper.year and paper.year > year_max:
                continue
            papers.append(paper)

        return papers


def _parse_work(item: dict) -> Paper:
    authors = []
    for a in item.get("authors", []):
        if isinstance(a, dict):
            authors.append(a.get("name", ""))
        elif isinstance(a, str):
            authors.append(a)

    doi = None
    for ident in item.get("identifiers", []):
        if isinstance(ident, str) and ident.startswith("10."):
            doi = ident
            break

    # Also check doi field directly
    if not doi:
        doi = item.get("doi")

    urls = item.get("links", [])
    pdf_url = None
    for link in urls:
        if isinstance(link, dict) and link.get("type") == "download":
            pdf_url = link.get("url")
            break

    return Paper(
        title=item.get("title", ""),
        authors=authors,
        abstract=item.get("abstract"),
        doi=doi,
        year=item.get("yearPublished"),
        url=item.get("downloadUrl") or item.get("sourceFulltextUrls", [None])[0] if item.get("sourceFulltextUrls") else None,
        pdf_url=pdf_url or item.get("downloadUrl"),
        is_open_access=True,  # CORE focuses on OA
        source="core",
        external_ids={"DOI": doi} if doi else {},
    )
