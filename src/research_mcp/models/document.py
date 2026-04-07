"""Document extraction models."""

from __future__ import annotations

from pydantic import BaseModel


class ExtractedTable(BaseModel):
    caption: str | None = None
    headers: list[str]
    rows: list[list[str]]
    page: int | None = None


class ExtractedDocument(BaseModel):
    content: str  # Main text as markdown
    tables: list[ExtractedTable] = []
    figures: list[str] = []  # Figure captions / descriptions
    title: str | None = None
    num_pages: int | None = None
    source_url: str | None = None
