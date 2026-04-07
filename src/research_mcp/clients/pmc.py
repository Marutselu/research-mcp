"""PubMed Central (PMC) client for open access full text."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from research_mcp.clients.http import NotFoundError, raise_for_status, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PMCClient:
    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self._client = http_client
        self._api_key = api_key

    def _key_param(self) -> dict:
        return {"api_key": self._api_key} if self._api_key else {}

    @with_retry(max_attempts=3)
    async def search(
        self,
        query: str,
        max_results: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[Paper]:
        term = f"{query} open access[filter]"
        if year_min or year_max:
            term += f" AND {year_min or 1900}:{year_max or 2100}[dp]"

        params = {
            "db": "pmc",
            "term": term,
            "retmax": max_results,
            "retmode": "json",
            **self._key_param(),
        }

        response = await self._client.get(f"{EUTILS_BASE}/esearch.fcgi", params=params)
        raise_for_status(response, source="pmc")
        data = response.json()

        pmcids = data.get("esearchresult", {}).get("idlist", [])
        if not pmcids:
            return []

        return await self._fetch_summaries(pmcids)

    async def get_by_pmcid(self, pmcid: str) -> Paper:
        pmcid_num = pmcid.replace("PMC", "")
        papers = await self._fetch_summaries([pmcid_num])
        if papers:
            return papers[0]
        raise NotFoundError(f"PMCID {pmcid} not found", source="pmc")

    async def get_pdf_url(self, pmcid: str) -> str | None:
        """Construct PDF URL for a PMC article."""
        if not pmcid.startswith("PMC"):
            pmcid = f"PMC{pmcid}"
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"

    async def _fetch_summaries(self, pmcids: list[str]) -> list[Paper]:
        params = {
            "db": "pmc",
            "id": ",".join(pmcids),
            "retmode": "json",
            **self._key_param(),
        }

        response = await self._client.get(f"{EUTILS_BASE}/esummary.fcgi", params=params)
        raise_for_status(response, source="pmc")
        data = response.json()

        papers = []
        result = data.get("result", {})
        for uid in result.get("uids", []):
            item = result.get(uid, {})
            if not isinstance(item, dict):
                continue
            papers.append(_parse_summary(uid, item))

        return papers


def _parse_summary(uid: str, item: dict) -> Paper:
    title = item.get("title", "")
    pmcid = f"PMC{uid}"

    authors = []
    for a in item.get("authors", []):
        name = a.get("name", "")
        if name:
            authors.append(name)

    year = None
    pub_date = item.get("pubdate", "")
    if pub_date and len(pub_date) >= 4:
        try:
            year = int(pub_date[:4])
        except ValueError:
            pass

    doi = None
    for aid in item.get("articleids", []):
        if aid.get("idtype") == "doi":
            doi = aid.get("value")
            break

    ext_ids: dict[str, str] = {"PMCID": pmcid}
    if doi:
        ext_ids["DOI"] = doi

    pmid = None
    for aid in item.get("articleids", []):
        if aid.get("idtype") == "pmid":
            pmid = aid.get("value")
            ext_ids["PubMed"] = pmid
            break

    return Paper(
        title=title,
        authors=authors,
        doi=doi,
        pmid=pmid,
        year=year,
        venue=item.get("fulljournalname"),
        url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/",
        pdf_url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/",
        is_open_access=True,
        source="pmc",
        external_ids=ext_ids,
    )
