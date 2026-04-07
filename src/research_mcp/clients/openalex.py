"""OpenAlex API client."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import fetch_json, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openalex.org"


class OpenAlexClient:
    def __init__(self, http_client: httpx.AsyncClient, mailto: str | None = None) -> None:
        self._client = http_client
        self._mailto = mailto

    def _params(self, extra: dict | None = None) -> dict:
        params: dict = {}
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
            "search": query,
            "per_page": max_results,
            "sort": "relevance_score:desc",
        })

        filters = []
        if year_min:
            filters.append(f"from_publication_date:{year_min}-01-01")
        if year_max:
            filters.append(f"to_publication_date:{year_max}-12-31")
        if filters:
            params["filter"] = ",".join(filters)

        data = await fetch_json(
            self._client, f"{BASE_URL}/works", source="openalex", params=params
        )

        return [_parse_work(item) for item in data.get("results", [])]


def _reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    # inverted_index is {word: [position, ...]}
    words: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            words.append((pos, word))
    words.sort()
    return " ".join(word for _, word in words)


def _parse_work(item: dict) -> Paper:
    # Authors
    authors = []
    for authorship in item.get("authorships", []):
        author = authorship.get("author", {})
        name = author.get("display_name", "")
        if name:
            authors.append(name)

    # Abstract
    abstract = None
    if item.get("abstract_inverted_index"):
        abstract = _reconstruct_abstract(item["abstract_inverted_index"])

    # DOI
    doi = item.get("doi")
    if doi and doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]

    # OA PDF
    pdf_url = None
    oa_location = item.get("primary_location", {})
    if oa_location:
        pdf_url = oa_location.get("pdf_url")

    # IDs
    openalex_id = item.get("id", "")
    ext_ids: dict[str, str] = {}
    if doi:
        ext_ids["DOI"] = doi
    if openalex_id:
        ext_ids["OpenAlex"] = openalex_id

    ids = item.get("ids", {})
    if ids.get("pmid"):
        pmid = ids["pmid"]
        if pmid.startswith("https://pubmed.ncbi.nlm.nih.gov/"):
            pmid = pmid.split("/")[-1]
        ext_ids["PubMed"] = pmid

    return Paper(
        title=item.get("display_name") or item.get("title", ""),
        authors=authors,
        abstract=abstract,
        doi=doi,
        year=item.get("publication_year"),
        venue=item.get("primary_location", {}).get("source", {}).get("display_name") if item.get("primary_location") else None,
        citation_count=item.get("cited_by_count"),
        url=item.get("doi") or openalex_id,
        pdf_url=pdf_url,
        is_open_access=item.get("open_access", {}).get("is_oa", False),
        source="openalex",
        external_ids=ext_ids,
    )
