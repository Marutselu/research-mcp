"""Wikidata API client for entity search and retrieval."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from research_mcp.clients.http import NotFoundError, fetch_json, with_retry
from research_mcp.models.search import NormalizedResult, SearchResponse

logger = logging.getLogger(__name__)

API_BASE = "https://www.wikidata.org/w/api.php"


class WikidataClient:
    """Client for Wikidata API operations."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    @with_retry(max_attempts=2)
    async def search(self, query: str, max_results: int = 10, language: str = "en") -> SearchResponse:
        """Search for Wikidata entities.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            language: Language code for labels and descriptions.

        Returns:
            SearchResponse with normalized results.
        """
        data = await fetch_json(
            self._client,
            API_BASE,
            source="wikidata",
            params={
                "action": "wbsearchentities",
                "search": query,
                "language": language,
                "format": "json",
                "limit": max_results,
            },
        )

        results = []
        for item in data.get("search", []):
            entity_id = item.get("id", "")
            results.append(
                NormalizedResult(
                    title=item.get("label", ""),
                    url=f"https://www.wikidata.org/wiki/{entity_id}",
                    snippet=item.get("description", ""),
                    source="wikidata",
                    content_type="knowledge_graph",
                    metadata={
                        "entity_id": entity_id,
                        "aliases": item.get("aliases", []),
                        "match_type": item.get("match", {}).get("type"),
                    },
                )
            )

        return SearchResponse(
            results=results,
            total=len(results),
            query=query,
        )

    @with_retry(max_attempts=2)
    async def get_entity(self, entity_id: str, language: str = "en") -> dict[str, Any]:
        """Fetch detailed information about a Wikidata entity.

        Args:
            entity_id: Wikidata entity ID (e.g., 'Q42' for Douglas Adams).
            language: Language code for labels and descriptions.

        Returns:
            Dictionary with entity data including labels, descriptions, claims, etc.

        Raises:
            NotFoundError: If the entity does not exist.
        """
        data = await fetch_json(
            self._client,
            API_BASE,
            source="wikidata",
            params={
                "action": "wbgetentities",
                "ids": entity_id,
                "format": "json",
                "languages": language,
                "props": "labels|descriptions|aliases|claims|sitelinks",
            },
        )

        entities = data.get("entities", {})
        if entity_id not in entities:
            raise NotFoundError(f"Wikidata entity not found: {entity_id}", source="wikidata")

        entity = entities[entity_id]

        # Check if entity is missing (exists but has no data)
        if "missing" in entity:
            raise NotFoundError(f"Wikidata entity not found: {entity_id}", source="wikidata")

        return _normalize_entity(entity, language)


def _normalize_entity(entity: dict[str, Any], language: str) -> dict[str, Any]:
    """Normalize Wikidata entity response to a cleaner structure."""
    labels = entity.get("labels", {})
    descriptions = entity.get("descriptions", {})
    aliases = entity.get("aliases", {})
    claims = entity.get("claims", {})
    sitelinks = entity.get("sitelinks", {})

    # Extract label and description in requested language
    label = labels.get(language, {}).get("value", "")
    description = descriptions.get(language, {}).get("value", "")

    # Extract aliases in requested language
    alias_list = [a.get("value", "") for a in aliases.get(language, [])]

    # Extract Wikipedia sitelink if available
    wiki_link = None
    for site, link_data in sitelinks.items():
        if site.endswith("wiki") and not site.startswith("wikidata"):
            wiki_link = (
                f"https://{site.replace('wiki', '.wikipedia.org/wiki/')}{link_data.get('title', '').replace(' ', '_')}"
            )
            break

    # Simplify claims to property-value pairs
    simplified_claims = {}
    for prop_id, claim_list in claims.items():
        values = []
        for claim in claim_list:
            mainsnak = claim.get("mainsnak", {})
            datatype = mainsnak.get("datatype")
            datavalue = mainsnak.get("datavalue", {})

            if datatype == "wikibase-item":
                # Reference to another Wikidata entity
                entity_id = datavalue.get("value", {}).get("id", "")
                if entity_id:
                    values.append({"type": "entity", "id": entity_id})
            elif datatype == "string":
                values.append({"type": "string", "value": datavalue.get("value", "")})
            elif datatype == "time":
                values.append({"type": "time", "value": datavalue.get("value", {}).get("time", "")})
            elif datatype == "quantity":
                amount = datavalue.get("value", {}).get("amount", "")
                unit = datavalue.get("value", {}).get("unit", "")
                values.append({"type": "quantity", "amount": amount, "unit": unit})
            elif datatype == "monolingualtext":
                text = datavalue.get("value", {}).get("text", "")
                values.append({"type": "text", "value": text})
            elif datatype == "external-id":
                values.append({"type": "external_id", "value": datavalue.get("value", "")})
            elif datatype == "url":
                values.append({"type": "url", "value": datavalue.get("value", "")})
            elif datatype == "coordinate":
                lat = datavalue.get("value", {}).get("latitude")
                lon = datavalue.get("value", {}).get("longitude")
                if lat is not None and lon is not None:
                    values.append({"type": "coordinate", "lat": lat, "lon": lon})

        if values:
            simplified_claims[prop_id] = values

    return {
        "id": entity.get("id", ""),
        "label": label,
        "description": description,
        "aliases": alias_list,
        "claims": simplified_claims,
        "sitelinks": {
            site: {
                "title": link_data.get("title", ""),
                "url": f"https://{site.replace('wiki', '.wikipedia.org/wiki/')}{link_data.get('title', '').replace(' ', '_')}"
                if site.endswith("wiki") and not site.startswith("wikidata")
                else None,
            }
            for site, link_data in sitelinks.items()
        },
        "wikipedia_url": wiki_link,
        "wikidata_url": f"https://www.wikidata.org/wiki/{entity.get('id', '')}",
    }
