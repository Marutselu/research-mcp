"""arXiv Atom/XML API client."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import httpx

from research_mcp.clients.http import APIError, raise_for_status, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


class ArxivClient:
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
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        response = await self._client.get(BASE_URL, params=params)
        raise_for_status(response, source="arxiv")

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as e:
            raise APIError(f"arXiv returned invalid XML: {e}", source="arxiv")
        papers = []
        for entry in root.findall(f"{ATOM_NS}entry"):
            paper = _parse_entry(entry)
            if paper:
                if year_min and paper.year and paper.year < year_min:
                    continue
                if year_max and paper.year and paper.year > year_max:
                    continue
                papers.append(paper)

        return papers

    @with_retry(max_attempts=3)
    async def get_by_id(self, arxiv_id: str) -> Paper | None:
        """Look up a specific paper by arXiv ID using id_list parameter."""
        params = {"id_list": arxiv_id, "max_results": 1}
        response = await self._client.get(BASE_URL, params=params)
        raise_for_status(response, source="arxiv")

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as e:
            raise APIError(f"arXiv returned invalid XML: {e}", source="arxiv")

        for entry in root.findall(f"{ATOM_NS}entry"):
            paper = _parse_entry(entry)
            if paper:
                return paper
        return None


def _parse_entry(entry: ET.Element) -> Paper | None:
    title_el = entry.find(f"{ATOM_NS}title")
    if title_el is None or not title_el.text:
        return None

    title = " ".join(title_el.text.strip().split())

    authors = []
    for author in entry.findall(f"{ATOM_NS}author"):
        name = author.find(f"{ATOM_NS}name")
        if name is not None and name.text:
            authors.append(name.text.strip())

    abstract_el = entry.find(f"{ATOM_NS}summary")
    abstract = " ".join(abstract_el.text.strip().split()) if abstract_el is not None and abstract_el.text else None

    # Extract arXiv ID from the entry ID URL
    id_el = entry.find(f"{ATOM_NS}id")
    arxiv_id = None
    url = None
    if id_el is not None and id_el.text:
        url = id_el.text.strip()
        match = re.search(r"abs/(.+)$", url)
        if match:
            arxiv_id = match.group(1)
            # Strip version for cleaner ID
            arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

    # Get PDF link
    pdf_url = None
    for link in entry.findall(f"{ATOM_NS}link"):
        if link.get("title") == "pdf":
            pdf_url = link.get("href")
            break

    # Extract year from published date
    published = entry.find(f"{ATOM_NS}published")
    year = None
    if published is not None and published.text:
        match = re.match(r"(\d{4})", published.text)
        if match:
            year = int(match.group(1))

    # Extract DOI if present
    doi_el = entry.find(f"{ARXIV_NS}doi")
    doi = doi_el.text.strip() if doi_el is not None and doi_el.text else None

    # Category / venue
    categories = []
    for cat in entry.findall(f"{ARXIV_NS}primary_category"):
        term = cat.get("term")
        if term:
            categories.append(term)

    return Paper(
        title=title,
        authors=authors,
        abstract=abstract,
        doi=doi,
        arxiv_id=arxiv_id,
        year=year,
        venue=", ".join(categories) if categories else None,
        url=url,
        pdf_url=pdf_url,
        is_open_access=True,  # All arXiv papers are OA
        source="arxiv",
        external_ids={"ArXiv": arxiv_id} if arxiv_id else {},
    )
