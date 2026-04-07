"""Academic paper models."""

from __future__ import annotations

from pydantic import BaseModel


class Author(BaseModel):
    name: str
    affiliation: str | None = None
    author_id: str | None = None


class Paper(BaseModel):
    title: str
    authors: list[str]
    abstract: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    year: int | None = None
    venue: str | None = None
    citation_count: int | None = None
    url: str | None = None
    pdf_url: str | None = None
    is_open_access: bool | None = None
    source: str
    external_ids: dict[str, str] = {}
