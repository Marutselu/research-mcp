"""Unpaywall DOI → OA PDF URL resolver."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import fetch_json, with_retry
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.unpaywall.org/v2"


class UnpaywallClient:
    def __init__(self, http_client: httpx.AsyncClient, email: str | None = None) -> None:
        self._client = http_client
        self._email = email

    @with_retry(max_attempts=2)
    async def get_oa_url(self, doi: str) -> str | None:
        """Resolve a DOI to the best open access PDF URL."""
        if not self._email:
            logger.debug("Unpaywall disabled: no email configured")
            return None

        data = await fetch_json(
            self._client,
            f"{BASE_URL}/{doi}",
            source="unpaywall",
            params={"email": self._email},
        )

        # Try best OA location
        best = data.get("best_oa_location")
        if best:
            pdf_url = best.get("url_for_pdf") or best.get("url")
            if pdf_url:
                return pdf_url

        # Try all OA locations
        for loc in data.get("oa_locations", []):
            pdf_url = loc.get("url_for_pdf")
            if pdf_url:
                return pdf_url

        return None

    async def search(self, **kwargs) -> list[Paper]:
        """Unpaywall doesn't support search — this is a no-op."""
        return []
