"""bioRxiv / medRxiv API client."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

from research_mcp.clients.http import fetch_json, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.biorxiv.org/details"


class BiorxivClient:
    def __init__(self, http_client: httpx.AsyncClient, server: str = "biorxiv") -> None:
        self._client = http_client
        self._server = server  # "biorxiv" or "medrxiv"

    @with_retry(max_attempts=3)
    async def search(
        self,
        query: str,
        max_results: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[Paper]:
        # bioRxiv API is date-range based, not full-text search
        # We search within a date window and filter by keyword in title/abstract
        end_date = datetime.now().strftime("%Y-%m-%d")
        if year_min:
            start_date = f"{year_min}-01-01"
        else:
            start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        data = await fetch_json(
            self._client,
            f"{BASE_URL}/{self._server}/{start_date}/{end_date}/0/{max_results * 3}",
            source=self._server,
        )

        # Filter by query keywords
        query_lower = query.lower()
        keywords = query_lower.split()

        papers = []
        for item in data.get("collection", []):
            title = item.get("title", "").lower()
            abstract = item.get("abstract", "").lower()
            text = f"{title} {abstract}"

            if any(kw in text for kw in keywords):
                paper = _parse_item(item, self._server)
                if year_max and paper.year and paper.year > year_max:
                    continue
                papers.append(paper)
                if len(papers) >= max_results:
                    break

        return papers


def _parse_item(item: dict, server: str) -> Paper:
    doi = item.get("doi")
    date_str = item.get("date", "")
    year = int(date_str[:4]) if date_str and len(date_str) >= 4 else None

    authors_str = item.get("authors", "")
    authors = [a.strip() for a in authors_str.split(";") if a.strip()] if authors_str else []

    return Paper(
        title=item.get("title", ""),
        authors=authors,
        abstract=item.get("abstract"),
        doi=doi,
        year=year,
        venue=server,
        url=f"https://doi.org/{doi}" if doi else None,
        pdf_url=f"https://www.{server}.org/content/{doi}v{item.get('version', '1')}.full.pdf" if doi else None,
        is_open_access=True,
        source=server,
        external_ids={"DOI": doi} if doi else {},
    )
