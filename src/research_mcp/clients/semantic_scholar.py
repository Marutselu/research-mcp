"""Semantic Scholar Graph API client."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import AuthenticationError, fetch_json, raise_for_status, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = "title,authors,abstract,year,venue,citationCount,url,openAccessPdf,externalIds"


class SemanticScholarClient:
    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self._client = http_client
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self._api_key:
            h["x-api-key"] = self._api_key
        return h

    @with_retry(max_attempts=4)
    async def search(
        self,
        query: str,
        max_results: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[Paper]:
        params: dict = {
            "query": query,
            "limit": min(max_results, 100),
            "fields": PAPER_FIELDS,
        }
        if year_min or year_max:
            year_range = f"{year_min or ''}-{year_max or ''}"
            params["year"] = year_range

        try:
            data = await fetch_json(
                self._client,
                f"{BASE_URL}/paper/search",
                source="semantic_scholar",
                params=params,
                headers=self._headers(),
            )
        except AuthenticationError:
            if self._api_key:
                logger.warning("S2 API key rejected, retrying without key")
                self._api_key = None
                data = await fetch_json(
                    self._client,
                    f"{BASE_URL}/paper/search",
                    source="semantic_scholar",
                    params=params,
                )
            else:
                raise

        return [_parse_paper(item) for item in data.get("data", [])]

    @with_retry(max_attempts=3)
    async def get_paper(self, paper_id: str) -> Paper:
        data = await fetch_json(
            self._client,
            f"{BASE_URL}/paper/{paper_id}",
            source="semantic_scholar",
            params={"fields": PAPER_FIELDS},
            headers=self._headers(),
        )
        return _parse_paper(data)

    @with_retry(max_attempts=3)
    async def get_citations(
        self,
        paper_id: str,
        direction: str = "cited_by",
        max_results: int = 20,
    ) -> list[Paper]:
        endpoint = "citations" if direction == "cited_by" else "references"
        data = await fetch_json(
            self._client,
            f"{BASE_URL}/paper/{paper_id}/{endpoint}",
            source="semantic_scholar",
            params={"fields": PAPER_FIELDS, "limit": min(max_results, 100)},
            headers=self._headers(),
        )
        key = "citingPaper" if direction == "cited_by" else "citedPaper"
        return [_parse_paper(item[key]) for item in data.get("data", []) if item.get(key)]


def _parse_paper(data: dict) -> Paper:
    ext_ids = data.get("externalIds") or {}
    oa_pdf = data.get("openAccessPdf") or {}
    authors = [a.get("name", "") for a in data.get("authors", [])]
    return Paper(
        title=data.get("title", ""),
        authors=authors,
        abstract=data.get("abstract"),
        doi=ext_ids.get("DOI"),
        arxiv_id=ext_ids.get("ArXiv"),
        pmid=ext_ids.get("PubMed"),
        year=data.get("year"),
        venue=data.get("venue"),
        citation_count=data.get("citationCount"),
        url=data.get("url"),
        pdf_url=oa_pdf.get("url"),
        is_open_access=bool(oa_pdf.get("url")),
        source="semantic_scholar",
        external_ids={k: str(v) for k, v in ext_ids.items() if v},
    )
