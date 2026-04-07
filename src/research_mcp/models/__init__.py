"""Shared Pydantic models used across layers."""

from research_mcp.models.academic import Author, Paper
from research_mcp.models.document import ExtractedDocument, ExtractedTable
from research_mcp.models.index import IndexEntry, SearchHit
from research_mcp.models.search import NormalizedResult, PaginatedContent, SearchResponse
from research_mcp.models.video import Transcript, VideoMetadata

__all__ = [
    "Author",
    "ExtractedDocument",
    "ExtractedTable",
    "IndexEntry",
    "NormalizedResult",
    "PaginatedContent",
    "Paper",
    "SearchHit",
    "SearchResponse",
    "Transcript",
    "VideoMetadata",
]
