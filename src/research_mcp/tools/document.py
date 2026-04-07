"""Document Extraction tools (Group 5: document)."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from research_mcp.cache import Cache
from research_mcp.models.document import ExtractedDocument
from research_mcp.models.search import PaginatedContent
from research_mcp.services.document import DocumentService


def register_document_tools(mcp: FastMCP) -> None:

    @mcp.tool(tags={"document"})
    async def research_extract_document(
        url_or_path: str,
        extract_tables: bool = True,
        extract_images: bool = False,
        start_index: int = 0,
        max_length: int = 20000,
        ctx: Context = None,
    ) -> str:
        """Extract text, tables, and figures from a PDF or document using Docling Serve.

        Provides layout-aware extraction with table structure preservation.

        Args:
            url_or_path: URL to a PDF or document, or a local file path.
            extract_tables: Include extracted tables in output.
            extract_images: Include figure descriptions in output.
            start_index: Character offset for pagination.
            max_length: Maximum characters to return.
        """
        service: DocumentService = ctx.lifespan_context["document_service"]

        doc = await service.extract_document(
            url_or_path,
            extract_tables=extract_tables,
            extract_images=extract_images,
        )

        # Build full output
        parts = [doc.content]
        if extract_tables and doc.tables:
            parts.append("\n\n## Extracted Tables\n")
            for i, table in enumerate(doc.tables, 1):
                if table.caption:
                    parts.append(f"\n### Table {i}: {table.caption}\n")
                else:
                    parts.append(f"\n### Table {i}\n")
                # Render as markdown table
                if table.headers:
                    parts.append("| " + " | ".join(table.headers) + " |")
                    parts.append("| " + " | ".join("---" for _ in table.headers) + " |")
                for row in table.rows:
                    parts.append("| " + " | ".join(row) + " |")

        full_text = "\n".join(parts)

        total = len(full_text)
        chunk = full_text[start_index : start_index + max_length]
        if start_index + len(chunk) < total:
            chunk += f"\n\n[Content truncated. Use start_index={start_index + len(chunk)} to continue reading.]"
        return chunk

    @mcp.tool(tags={"document"})
    async def research_extract_article(
        url: str,
        start_index: int = 0,
        max_length: int = 20000,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> PaginatedContent:
        """Extract the main article content from a web page, removing navigation, ads, and sidebars.

        Uses readability-style content extraction — no Docling needed.

        Args:
            url: Article URL.
            start_index: Character offset for pagination.
            max_length: Maximum characters to return.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: DocumentService = ctx.lifespan_context["document_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_extract_article", {"url": url})

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return _paginate(cached["content"], start_index, max_length)

        content = await service.extract_article(url)
        cache.set(cache_key, {"content": content}, ttl_seconds=config.cache.ttl.web_pages, source="extract_article")
        return _paginate(content, start_index, max_length)


def _paginate(content: str, start_index: int, max_length: int) -> PaginatedContent:
    total = len(content)
    chunk = content[start_index : start_index + max_length]
    return PaginatedContent(
        content=chunk,
        total_length=total,
        start_index=start_index,
        retrieved_length=len(chunk),
        is_truncated=start_index + len(chunk) < total,
        has_more=start_index + len(chunk) < total,
    )
