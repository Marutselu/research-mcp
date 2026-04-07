"""PubMed E-utilities client."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from research_mcp.clients.http import raise_for_status, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedClient:
    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self._client = http_client
        self._api_key = api_key

    def _params(self, extra: dict | None = None) -> dict:
        params: dict = {"db": "pubmed", "retmode": "json"}
        if self._api_key:
            params["api_key"] = self._api_key
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
        # Add year filter to query
        term = query
        if year_min or year_max:
            date_filter = f"{year_min or 1900}:{year_max or 2100}[dp]"
            term = f"{query} AND {date_filter}"

        # Step 1: Search for PMIDs
        search_params = self._params({
            "term": term,
            "retmax": max_results,
            "sort": "relevance",
        })
        response = await self._client.get(f"{EUTILS_BASE}/esearch.fcgi", params=search_params)
        raise_for_status(response, source="pubmed")
        search_data = response.json()

        pmids = search_data.get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return []

        # Step 2: Fetch metadata for PMIDs
        return await self._fetch_papers(pmids)

    @with_retry(max_attempts=3)
    async def get_by_pmid(self, pmid: str) -> Paper:
        papers = await self._fetch_papers([pmid])
        if papers:
            return papers[0]
        from research_mcp.clients.http import NotFoundError
        raise NotFoundError(f"PMID {pmid} not found", source="pubmed")

    async def _fetch_papers(self, pmids: list[str]) -> list[Paper]:
        """Fetch paper metadata from PubMed for a list of PMIDs."""
        fetch_params: dict = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "rettype": "abstract",
            "retmode": "xml",
        }
        if self._api_key:
            fetch_params["api_key"] = self._api_key

        response = await self._client.get(f"{EUTILS_BASE}/efetch.fcgi", params=fetch_params)
        raise_for_status(response, source="pubmed")

        root = ET.fromstring(response.text)
        papers = []

        for article in root.findall(".//PubmedArticle"):
            paper = _parse_pubmed_article(article)
            if paper:
                papers.append(paper)

        return papers


def _parse_pubmed_article(article: ET.Element) -> Paper | None:
    medline = article.find(".//MedlineCitation")
    if medline is None:
        return None

    pmid_el = medline.find(".//PMID")
    pmid = pmid_el.text if pmid_el is not None else None

    art = medline.find(".//Article")
    if art is None:
        return None

    title_el = art.find(".//ArticleTitle")
    title = title_el.text if title_el is not None and title_el.text else ""

    # Authors
    authors = []
    for author in art.findall(".//Author"):
        last = author.find("LastName")
        first = author.find("ForeName")
        if last is not None and last.text:
            name = last.text
            if first is not None and first.text:
                name = f"{first.text} {last.text}"
            authors.append(name)

    # Abstract
    abstract_parts = []
    for text in art.findall(".//AbstractText"):
        if text.text:
            label = text.get("Label", "")
            if label:
                abstract_parts.append(f"{label}: {text.text}")
            else:
                abstract_parts.append(text.text)
    abstract = " ".join(abstract_parts) if abstract_parts else None

    # Year
    year = None
    pub_date = art.find(".//PubDate")
    if pub_date is not None:
        year_el = pub_date.find("Year")
        if year_el is not None and year_el.text:
            year = int(year_el.text)

    # DOI
    doi = None
    for eid in article.findall(".//ArticleId"):
        if eid.get("IdType") == "doi" and eid.text:
            doi = eid.text
            break

    # Venue
    journal = art.find(".//Journal/Title")
    venue = journal.text if journal is not None else None

    ext_ids: dict[str, str] = {}
    if pmid:
        ext_ids["PubMed"] = pmid
    if doi:
        ext_ids["DOI"] = doi

    return Paper(
        title=title,
        authors=authors,
        abstract=abstract,
        doi=doi,
        pmid=pmid,
        year=year,
        venue=venue,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
        is_open_access=None,
        source="pubmed",
        external_ids=ext_ids,
    )
