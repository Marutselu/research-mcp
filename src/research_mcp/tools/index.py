"""Local Vector Index tools (Group 7: vector_index)."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from research_mcp.models.index import IndexEntry, SearchHit
from research_mcp.services.vector_index import VectorIndexService


def register_index_tools(mcp: FastMCP) -> None:

    @mcp.tool(tags={"vector_index"})
    async def research_index_save(
        content: str,
        title: str,
        url: str | None = None,
        source_type: str = "webpage",
        tags: list[str] | None = None,
        ctx: Context = None,
    ) -> str:
        """Save content to the local vector index for later semantic retrieval.

        Embeds the content using Ollama and stores it in a local SQLite database.

        Args:
            content: The text content to save and index.
            title: A descriptive title for this entry.
            url: Source URL (if applicable).
            source_type: Type of content - 'paper', 'transcript', 'webpage', or 'document'.
            tags: Optional tags for filtering (e.g., ['machine-learning', 'tutorial']).
        """
        service: VectorIndexService = ctx.lifespan_context["vector_index_service"]

        entry_id = await service.save(
            content=content,
            title=title,
            url=url,
            source_type=source_type,
            tags=tags or [],
        )
        return f"Saved to index with ID: {entry_id}"

    @mcp.tool(tags={"vector_index"})
    async def research_index_search(
        query: str,
        source_type: str | None = None,
        tags: list[str] | None = None,
        top_k: int = 10,
        ctx: Context = None,
    ) -> list[SearchHit]:
        """Semantic search over saved transcripts, papers, pages, and documents.

        Args:
            query: Natural language search query.
            source_type: Filter by type - 'paper', 'transcript', 'webpage', 'document'.
            tags: Filter by tags.
            top_k: Maximum number of results.
        """
        service: VectorIndexService = ctx.lifespan_context["vector_index_service"]
        return await service.search(
            query=query,
            source_type=source_type,
            tags=tags,
            top_k=top_k,
        )

    @mcp.tool(tags={"vector_index"})
    async def research_index_list(
        source_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
        ctx: Context = None,
    ) -> list[IndexEntry]:
        """List entries saved in the local vector index.

        Args:
            source_type: Filter by type - 'paper', 'transcript', 'webpage', 'document'.
            limit: Maximum entries to return.
            offset: Skip this many entries (for pagination).
        """
        service: VectorIndexService = ctx.lifespan_context["vector_index_service"]
        return await service.list_entries(source_type=source_type, limit=limit, offset=offset)

    @mcp.tool(tags={"vector_index"})
    async def research_index_delete(
        entry_id: str,
        ctx: Context = None,
    ) -> str:
        """Remove an entry from the local vector index.

        Args:
            entry_id: The ID of the entry to delete.
        """
        service: VectorIndexService = ctx.lifespan_context["vector_index_service"]
        await service.delete(entry_id)
        return f"Deleted entry {entry_id}"
