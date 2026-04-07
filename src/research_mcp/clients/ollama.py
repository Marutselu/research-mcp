"""Ollama embedding API client."""

from __future__ import annotations

import logging

import httpx

from research_mcp.clients.http import APIError, raise_for_status

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, http_client: httpx.AsyncClient, base_url: str, model: str) -> None:
        self._client = http_client
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def embed(self, text: str) -> list[float]:
        """Compute embedding for a single text string."""
        try:
            response = await self._client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": text},
                timeout=60.0,
            )
            raise_for_status(response, source="ollama")
            data = response.json()

            embeddings = data.get("embeddings", [])
            if embeddings:
                return embeddings[0]

            raise APIError("No embeddings returned from Ollama", source="ollama")

        except httpx.ConnectError:
            raise APIError(
                f"Cannot connect to Ollama at {self._base_url}. Is it running?",
                source="ollama",
            )

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for multiple texts."""
        try:
            response = await self._client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": texts},
                timeout=120.0,
            )
            raise_for_status(response, source="ollama")
            data = response.json()

            return data.get("embeddings", [])

        except httpx.ConnectError:
            raise APIError(
                f"Cannot connect to Ollama at {self._base_url}. Is it running?",
                source="ollama",
            )

    async def is_available(self) -> bool:
        """Check if Ollama is reachable and the model exists."""
        try:
            response = await self._client.get(f"{self._base_url}/api/tags", timeout=5.0)
            return response.is_success
        except Exception:
            return False
