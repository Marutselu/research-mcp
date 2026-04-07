"""Academic search service: multi-source fan-out, deduplication, DOI resolution."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from research_mcp.clients.http import APIError, ServiceError
from research_mcp.config import ResearchMCPConfig
from research_mcp.models.academic import Paper

logger = logging.getLogger(__name__)

# Registry of source name -> client class
_SOURCE_REGISTRY: dict[str, type] = {}


def _register_source(name: str):
    """Decorator to register an academic source client class."""
    def decorator(cls):
        _SOURCE_REGISTRY[name] = cls
        return cls
    return decorator


def _detect_id_type(paper_id: str) -> str:
    """Detect the type of paper identifier."""
    paper_id = paper_id.strip()
    if paper_id.startswith("10."):
        return "doi"
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", paper_id):
        return "arxiv"
    if paper_id.startswith("PMC"):
        return "pmcid"
    if paper_id.isdigit() and len(paper_id) <= 8:
        return "pmid"
    # Assume Semantic Scholar ID
    return "s2"


def _normalize_title(title: str) -> str:
    """Normalize a title for deduplication comparison."""
    return re.sub(r"[^a-z0-9\s]", "", title.lower()).strip()


class AcademicSearchService:
    def __init__(self, http_client: httpx.AsyncClient, config: ResearchMCPConfig) -> None:
        self._http = http_client
        self._config = config
        self._clients: dict[str, Any] = {}
        self._init_clients()

    def _init_clients(self) -> None:
        """Initialize all academic source clients."""
        from research_mcp.clients.semantic_scholar import SemanticScholarClient
        from research_mcp.clients.arxiv import ArxivClient
        from research_mcp.clients.crossref import CrossrefClient
        from research_mcp.clients.core_api import CoreClient
        from research_mcp.clients.pubmed import PubMedClient
        from research_mcp.clients.europepmc import EuropePMCClient
        from research_mcp.clients.openalex import OpenAlexClient
        from research_mcp.clients.biorxiv import BiorxivClient
        from research_mcp.clients.doaj import DOAJClient
        from research_mcp.clients.dblp import DBLPClient
        from research_mcp.clients.pmc import PMCClient
        from research_mcp.clients.unpaywall import UnpaywallClient

        self._clients = {
            "semantic_scholar": SemanticScholarClient(self._http, self._config.semantic_scholar_api_key),
            "arxiv": ArxivClient(self._http),
            "crossref": CrossrefClient(self._http, self._config.crossref_mailto),
            "core": CoreClient(self._http, self._config.core_api_key),
            "pubmed": PubMedClient(self._http, self._config.pubmed_api_key),
            "europepmc": EuropePMCClient(self._http),
            "openalex": OpenAlexClient(self._http, self._config.crossref_mailto),
            "biorxiv": BiorxivClient(self._http),
            "medrxiv": BiorxivClient(self._http, server="medrxiv"),
            "doaj": DOAJClient(self._http, self._config.doaj_api_key),
            "dblp": DBLPClient(self._http),
            "pmc": PMCClient(self._http, self._config.pubmed_api_key),
            "unpaywall": UnpaywallClient(self._http, self._config.unpaywall_email),
        }

    async def search(
        self,
        query: str,
        sources: list[str],
        year_min: int | None = None,
        year_max: int | None = None,
        open_access_only: bool = False,
        max_results: int = 10,
    ) -> list[Paper]:
        """Fan-out search across multiple academic sources, merge and deduplicate."""
        # Filter to valid sources (exclude unpaywall from search — it's DOI-only)
        searchable = [s for s in sources if s in self._clients and s != "unpaywall"]

        per_source = self._config.academic.max_results_per_source

        async def _search_one(source_name: str) -> list[Paper]:
            client = self._clients[source_name]
            try:
                papers = await client.search(
                    query=query,
                    max_results=per_source,
                    year_min=year_min,
                    year_max=year_max,
                )
                logger.info("Source '%s' returned %d papers", source_name, len(papers))
                return papers
            except Exception as e:
                logger.warning("Source '%s' failed: %s", source_name, e)
                return []

        # Fan out to all sources concurrently
        all_results = await asyncio.gather(*[_search_one(s) for s in searchable])

        # Flatten
        all_papers: list[Paper] = []
        for papers in all_results:
            all_papers.extend(papers)

        # Deduplicate
        deduped = self._deduplicate(all_papers)

        # Filter OA
        if open_access_only:
            deduped = [p for p in deduped if p.is_open_access]

        # Sort by citation count (descending), fallback to year
        deduped.sort(key=lambda p: (p.citation_count or 0, p.year or 0), reverse=True)

        return deduped[:max_results]

    async def get_paper_details(self, paper_id: str) -> Paper:
        """Get detailed metadata for a paper by any identifier type."""
        id_type = _detect_id_type(paper_id)

        # Route to the best source for this ID type
        if id_type == "doi":
            return await self._resolve_by_doi(paper_id)
        elif id_type == "arxiv":
            client = self._clients.get("arxiv")
            if client:
                papers = await client.search(query=f"id:{paper_id}", max_results=1)
                if papers:
                    return papers[0]
        elif id_type == "pmid":
            client = self._clients.get("pubmed")
            if client:
                return await client.get_by_pmid(paper_id)
        elif id_type == "pmcid":
            client = self._clients.get("pmc")
            if client:
                return await client.get_by_pmcid(paper_id)

        # Fallback: try Semantic Scholar which accepts many ID types
        s2 = self._clients.get("semantic_scholar")
        if s2:
            return await s2.get_paper(paper_id)

        raise ServiceError(f"Could not resolve paper ID: {paper_id}")

    async def get_citations(
        self,
        paper_id: str,
        direction: str = "cited_by",
        max_results: int = 20,
    ) -> list[Paper]:
        """Get citing or referenced papers via Semantic Scholar."""
        s2 = self._clients.get("semantic_scholar")
        if not s2:
            raise ServiceError("Semantic Scholar client not available for citation lookup")
        return await s2.get_citations(paper_id, direction=direction, max_results=max_results)

    async def resolve_doi(self, doi: str) -> Paper:
        """Resolve a DOI to full metadata + OA PDF URL."""
        return await self._resolve_by_doi(doi)

    async def download_paper(
        self,
        paper_id_or_doi: str,
        output_format: str = "markdown",
        document_service: Any = None,
    ) -> str:
        """Find an OA PDF and extract text. Returns URL if extraction unavailable."""
        # First get paper details to find PDF URL
        paper = await self.get_paper_details(paper_id_or_doi)

        # Try to find an OA PDF via fallback chain
        pdf_url = paper.pdf_url
        if not pdf_url:
            pdf_url = await self._find_oa_pdf(paper)

        if not pdf_url:
            return f"No open access PDF found for: {paper.title}\nDOI: {paper.doi or 'N/A'}\nURL: {paper.url or 'N/A'}"

        # If document service is available, extract text
        if document_service:
            try:
                doc = await document_service.extract_document(pdf_url)
                return doc.content
            except Exception as e:
                logger.warning("Docling extraction failed: %s", e)

        return (
            f"PDF found but text extraction unavailable (Docling Serve not configured).\n\n"
            f"Title: {paper.title}\n"
            f"PDF URL: {pdf_url}\n"
            f"DOI: {paper.doi or 'N/A'}"
        )

    async def _resolve_by_doi(self, doi: str) -> Paper:
        """Resolve DOI via Crossref + enrich with Unpaywall."""
        crossref = self._clients.get("crossref")
        unpaywall = self._clients.get("unpaywall")

        paper = None
        if crossref:
            try:
                paper = await crossref.get_by_doi(doi)
            except Exception as e:
                logger.warning("Crossref DOI resolution failed: %s", e)

        # Enrich with Unpaywall OA info
        if paper and unpaywall and not paper.pdf_url:
            try:
                oa_url = await unpaywall.get_oa_url(doi)
                if oa_url:
                    paper.pdf_url = oa_url
                    paper.is_open_access = True
            except Exception as e:
                logger.debug("Unpaywall lookup failed: %s", e)

        if paper:
            return paper

        # Fallback to Semantic Scholar
        s2 = self._clients.get("semantic_scholar")
        if s2:
            return await s2.get_paper(f"DOI:{doi}")

        raise ServiceError(f"Could not resolve DOI: {doi}")

    async def _find_oa_pdf(self, paper: Paper) -> str | None:
        """Try multiple sources to find an OA PDF URL."""
        doi = paper.doi

        # 1. Try Unpaywall
        if doi:
            unpaywall = self._clients.get("unpaywall")
            if unpaywall:
                try:
                    url = await unpaywall.get_oa_url(doi)
                    if url:
                        return url
                except Exception:
                    pass

        # 2. Try Europe PMC
        if paper.pmid or doi:
            europepmc = self._clients.get("europepmc")
            if europepmc:
                try:
                    url = await europepmc.get_pdf_url(paper.pmid or doi)
                    if url:
                        return url
                except Exception:
                    pass

        # 3. Try PMC
        if paper.external_ids.get("pmcid"):
            pmc = self._clients.get("pmc")
            if pmc:
                try:
                    url = await pmc.get_pdf_url(paper.external_ids["pmcid"])
                    if url:
                        return url
                except Exception:
                    pass

        return None

    def _deduplicate(self, papers: list[Paper]) -> list[Paper]:
        """Deduplicate papers by DOI (primary) then normalized title."""
        seen_dois: dict[str, Paper] = {}
        seen_titles: dict[str, Paper] = {}
        deduped: list[Paper] = []

        for paper in papers:
            # DOI-based dedup
            if paper.doi:
                doi_lower = paper.doi.lower()
                if doi_lower in seen_dois:
                    existing = seen_dois[doi_lower]
                    # Merge: keep the one with more info
                    self._merge_paper(existing, paper)
                    continue
                seen_dois[doi_lower] = paper
                deduped.append(paper)
                continue

            # Title-based dedup
            norm_title = _normalize_title(paper.title)
            if norm_title and norm_title in seen_titles:
                existing = seen_titles[norm_title]
                self._merge_paper(existing, paper)
                continue

            if norm_title:
                seen_titles[norm_title] = paper
            deduped.append(paper)

        return deduped

    def _merge_paper(self, target: Paper, source: Paper) -> None:
        """Merge fields from source into target where target is missing data."""
        if not target.abstract and source.abstract:
            target.abstract = source.abstract
        if not target.doi and source.doi:
            target.doi = source.doi
        if not target.pdf_url and source.pdf_url:
            target.pdf_url = source.pdf_url
        if not target.citation_count and source.citation_count:
            target.citation_count = source.citation_count
        if source.is_open_access and not target.is_open_access:
            target.is_open_access = True
        # Merge external IDs
        for k, v in source.external_ids.items():
            if k not in target.external_ids:
                target.external_ids[k] = v
