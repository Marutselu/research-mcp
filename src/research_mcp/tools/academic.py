"""Academic Search tools (Group 2: academic)."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from research_mcp.cache import Cache
from research_mcp.models.academic import Paper
from research_mcp.services.academic_search import AcademicSearchService


def register_academic_tools(mcp: FastMCP) -> None:

    @mcp.tool(tags={"academic"})
    async def research_academic_search(
        query: str,
        sources: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        open_access_only: bool = False,
        max_results: int = 10,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> list[Paper]:
        """Search for academic papers across multiple sources simultaneously.

        Queries up to 13 academic databases, merges and deduplicates results.

        Args:
            query: Search query (title, topic, keywords).
            sources: Which sources to search. Defaults to config. Options: semantic_scholar, arxiv, crossref, core, pubmed, europepmc, openalex, biorxiv, medrxiv, doaj, dblp, pmc.
            year_min: Filter papers published after this year.
            year_max: Filter papers published before this year.
            open_access_only: Only return open access papers.
            max_results: Maximum total results after deduplication.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: AcademicSearchService = ctx.lifespan_context["academic_service"]
        config = ctx.lifespan_context["config"]

        if sources is None:
            sources = config.academic.default_sources

        cache_key = cache.make_key("research_academic_search", {
            "query": query, "sources": sorted(sources), "year_min": year_min,
            "year_max": year_max, "open_access_only": open_access_only, "max_results": max_results,
        })

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return [Paper(**p) for p in cached]

        papers = await service.search(
            query=query,
            sources=sources,
            year_min=year_min,
            year_max=year_max,
            open_access_only=open_access_only,
            max_results=max_results,
        )

        cache.set(
            cache_key,
            [p.model_dump() for p in papers],
            ttl_seconds=config.cache.ttl.academic,
            source="academic_search",
        )
        return papers

    @mcp.tool(tags={"academic"})
    async def research_paper_details(
        paper_id: str,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> Paper:
        """Get detailed metadata for a specific paper by any identifier.

        Args:
            paper_id: Paper identifier — DOI (10.xxx/yyy), arXiv ID (2301.12345), Semantic Scholar ID, PMID, or PMCID.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: AcademicSearchService = ctx.lifespan_context["academic_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_paper_details", {"paper_id": paper_id})

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return Paper(**cached)

        paper = await service.get_paper_details(paper_id)
        cache.set(cache_key, paper.model_dump(), ttl_seconds=config.cache.ttl.academic, source="paper_details")
        return paper

    @mcp.tool(tags={"academic"})
    async def research_paper_citations(
        paper_id: str,
        direction: str = "cited_by",
        max_results: int = 20,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> list[Paper]:
        """Get papers that cite or are cited by a given paper.

        Args:
            paper_id: Paper identifier (DOI, arXiv ID, S2 ID, PMID).
            direction: 'cited_by' for papers citing this one, 'references' for papers this one cites.
            max_results: Maximum results.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: AcademicSearchService = ctx.lifespan_context["academic_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_paper_citations", {
            "paper_id": paper_id, "direction": direction, "max_results": max_results,
        })

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return [Paper(**p) for p in cached]

        papers = await service.get_citations(paper_id, direction=direction, max_results=max_results)
        cache.set(
            cache_key,
            [p.model_dump() for p in papers],
            ttl_seconds=config.cache.ttl.academic,
            source="paper_citations",
        )
        return papers

    @mcp.tool(tags={"academic"})
    async def research_resolve_doi(
        doi: str,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> Paper:
        """Resolve a DOI to full paper metadata and open access PDF URL.

        Uses Crossref for metadata and Unpaywall for OA PDF discovery.

        Args:
            doi: The DOI to resolve (e.g., '10.1038/s41586-021-03819-2').
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: AcademicSearchService = ctx.lifespan_context["academic_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_resolve_doi", {"doi": doi})

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return Paper(**cached)

        paper = await service.resolve_doi(doi)
        cache.set(cache_key, paper.model_dump(), ttl_seconds=config.cache.ttl.academic, source="resolve_doi")
        return paper

    @mcp.tool(tags={"academic"})
    async def research_download_paper(
        paper_id_or_doi: str,
        output_format: str = "markdown",
        start_index: int = 0,
        max_length: int = 20000,
        ctx: Context = None,
    ) -> str:
        """Download and extract the full text of an academic paper.

        Tries multiple sources to find an open access PDF, then extracts text via Docling Serve.
        If Docling is unavailable, returns the best OA PDF URL found.

        Args:
            paper_id_or_doi: Paper identifier or DOI.
            output_format: Output format - 'markdown' or 'text'.
            start_index: Character offset for pagination.
            max_length: Maximum characters to return.
        """
        service: AcademicSearchService = ctx.lifespan_context["academic_service"]
        document_service = ctx.lifespan_context.get("document_service")

        result = await service.download_paper(
            paper_id_or_doi,
            output_format=output_format,
            document_service=document_service,
        )

        # Paginate the result
        total = len(result)
        chunk = result[start_index : start_index + max_length]
        if len(chunk) < total - start_index:
            chunk += f"\n\n[Content truncated. Use start_index={start_index + len(chunk)} to continue reading.]"
        return chunk
