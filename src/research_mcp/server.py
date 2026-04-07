"""FastMCP server creation, lifespan management, and tool group registration."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastmcp import FastMCP

from research_mcp.cache import Cache
from research_mcp.clients.http import create_http_client
from research_mcp.config import ResearchMCPConfig

logger = logging.getLogger(__name__)


def _check_optional_dep(module_name: str) -> bool:
    """Check if an optional dependency is importable."""
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


# Map group names to their required optional dependencies
GROUP_DEPENDENCIES: dict[str, list[str]] = {
    "web_search": ["scrapling", "markdownify"],
    "academic": [],  # Only needs httpx (core dep)
    "video": ["youtube_transcript_api", "yt_dlp"],
    "github_docs": [],  # Only needs httpx
    "document": [],  # Docling is external, markdownify for article extraction
    "wikipedia": [],  # Only needs httpx
    "vector_index": ["sqlite_vec"],
}


def compute_disabled_groups(config: ResearchMCPConfig) -> set[str]:
    """Determine which groups should be disabled (config + missing deps)."""
    disabled: set[str] = set()

    groups = config.groups.model_dump()
    for group_name, enabled in groups.items():
        if not enabled:
            logger.info("Group '%s' disabled by config", group_name)
            disabled.add(group_name)
            continue

        required_deps = GROUP_DEPENDENCIES.get(group_name, [])
        missing = [dep for dep in required_deps if not _check_optional_dep(dep)]
        if missing:
            logger.warning(
                "Group '%s' disabled: missing dependencies %s. "
                "Install with: pip install 'research-mcp[%s]'",
                group_name,
                missing,
                group_name if group_name != "vector_index" else "index",
            )
            disabled.add(group_name)

    return disabled


def make_lifespan(config: ResearchMCPConfig):
    """Create a lifespan context manager factory for FastMCP."""

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
        """Initialize and tear down shared resources."""
        http_client = create_http_client(timeout=config.scraping.timeout_seconds)
        cache_inst = Cache(config.cache)
        cache_inst.initialize()

        context: dict = {
            "config": config,
            "http_client": http_client,
            "cache": cache_inst,
        }

        # Initialize services based on enabled groups
        disabled = compute_disabled_groups(config)

        if "web_search" not in disabled:
            from research_mcp.clients.searxng import SearXNGClient
            from research_mcp.clients.scrapling_client import ScraplingClient
            from research_mcp.services.scraper import ScraperService
            from research_mcp.services.web_search import WebSearchService

            searxng_client = SearXNGClient(http_client, config.services.searxng_url)
            scrapling_client = ScraplingClient(config.scraping)
            context["searxng_client"] = searxng_client
            context["scrapling_client"] = scrapling_client
            context["web_search_service"] = WebSearchService(searxng_client, config.domains)
            context["scraper_service"] = ScraperService(scrapling_client, config.scraping)

        if "academic" not in disabled:
            from research_mcp.services.academic_search import AcademicSearchService

            context["academic_service"] = AcademicSearchService(http_client, config)

        if "video" not in disabled:
            from research_mcp.services.video import VideoService

            context["video_service"] = VideoService(config)

        if "github_docs" not in disabled:
            from research_mcp.services.github_docs import GitHubDocsService

            context["github_docs_service"] = GitHubDocsService(http_client, config)

        if "document" not in disabled:
            from research_mcp.services.document import DocumentService

            context["document_service"] = DocumentService(http_client, config)

        if "wikipedia" not in disabled:
            from research_mcp.services.wiki import WikiService

            context["wiki_service"] = WikiService(http_client)

        if "vector_index" not in disabled:
            from research_mcp.services.vector_index import VectorIndexService

            vector_service = VectorIndexService(config)
            await vector_service.initialize()
            context["vector_index_service"] = vector_service

        try:
            yield context
        finally:
            await http_client.aclose()
            cache_inst.close()
            if "vector_index_service" in context:
                context["vector_index_service"].close()

    return lifespan


def create_server(config: ResearchMCPConfig) -> FastMCP:
    """Create the FastMCP server with all tool groups registered."""
    mcp = FastMCP(
        "research-mcp",
        lifespan=make_lifespan(config),
    )

    # Register all tools (each tagged with their group)
    from research_mcp.tools import register_all_tools

    register_all_tools(mcp)

    # Disable groups that are turned off in config or missing deps
    disabled = compute_disabled_groups(config)
    for group in disabled:
        mcp.disable(tags={group})

    return mcp
