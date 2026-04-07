"""Universal search result models used across all tool groups."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class NormalizedResult(BaseModel):
    title: str
    url: str | None = None
    snippet: str
    source: str
    content_type: str
    date: str | None = None
    score: float | None = None
    metadata: dict[str, Any] = {}


class SearchResponse(BaseModel):
    results: list[NormalizedResult]
    total: int
    query: str
    has_more: bool = False
    next_offset: int | None = None


class PaginatedContent(BaseModel):
    content: str
    total_length: int
    start_index: int
    retrieved_length: int
    is_truncated: bool
    has_more: bool

    @property
    def next_start_index(self) -> int | None:
        if self.has_more:
            return self.start_index + self.retrieved_length
        return None
