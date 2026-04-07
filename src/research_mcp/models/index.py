"""Vector index models."""

from __future__ import annotations

from pydantic import BaseModel


class IndexEntry(BaseModel):
    id: str
    title: str
    url: str | None = None
    source_type: str  # paper, transcript, webpage, document
    tags: list[str] = []
    created_at: str  # ISO 8601
    content_preview: str | None = None  # First ~200 chars


class SearchHit(BaseModel):
    entry: IndexEntry
    score: float
    snippet: str  # Relevant content excerpt
