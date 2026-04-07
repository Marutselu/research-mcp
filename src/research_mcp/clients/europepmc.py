"""Europe PMC REST API client."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import fetch_json, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"


class EuropePMCClient:
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
        q = query
        if year_min or year_max:
            q += f" AND (PUB_YEAR:[{year_min or 1900} TO {year_max or 2100}])"

        data = await fetch_json(
            self._client,
            f"{BASE_URL}/search",
            source="europepmc",
            params={
                "query": q,
                "format": "json",
                "pageSize": max_results,
                "resultType": "core",
            },
        )

        papers = []
        for item in data.get("resultList", {}).get("result", []):
            papers.append(_parse_result(item))

        return papers

    async def get_pdf_url(self, identifier: str) -> str | None:
        """Try to find a full text PDF URL for a given identifier."""
        try:
            data = await fetch_json(
                self._client,
                f"{BASE_URL}/search",
                source="europepmc",
                params={"query": f"EXT_ID:{identifier}", "format": "json", "pageSize": 1},
            )
            results = data.get("resultList", {}).get("result", [])
            if results:
                for url_info in results[0].get("fullTextUrlList", {}).get("fullTextUrl", []):
                    if url_info.get("documentStyle") == "pdf":
                        return url_info.get("url")
        except Exception as e:
            logger.debug("Europe PMC PDF lookup failed: %s", e)
        return None


def _parse_result(item: dict) -> Paper:
    authors = []
    for a in item.get("authorList", {}).get("author", []):
        name = a.get("fullName", "")
        if name:
            authors.append(name)

    doi = item.get("doi")
    pmid = item.get("pmid")
    pmcid = item.get("pmcid")

    # Find PDF URL
    pdf_url = None
    for url_info in item.get("fullTextUrlList", {}).get("fullTextUrl", []):
        if url_info.get("documentStyle") == "pdf":
            pdf_url = url_info.get("url")
            break

    ext_ids: dict[str, str] = {}
    if doi:
        ext_ids["DOI"] = doi
    if pmid:
        ext_ids["PubMed"] = pmid
    if pmcid:
        ext_ids["PMCID"] = pmcid

    return Paper(
        title=item.get("title", ""),
        authors=authors,
        abstract=item.get("abstractText"),
        doi=doi,
        pmid=pmid,
        year=int(item["pubYear"]) if item.get("pubYear") else None,
        venue=item.get("journalTitle"),
        citation_count=item.get("citedByCount"),
        url=f"https://europepmc.org/article/{item.get('source', 'MED')}/{item.get('id', '')}",
        pdf_url=pdf_url,
        is_open_access=item.get("isOpenAccess") == "Y",
        source="europepmc",
        external_ids=ext_ids,
    )
