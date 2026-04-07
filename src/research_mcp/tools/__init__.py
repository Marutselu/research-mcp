"""Tool registration dispatcher."""

from __future__ import annotations

from fastmcp import FastMCP


def register_all_tools(mcp: FastMCP) -> None:
    """Register all tool groups with their tags."""
    from research_mcp.tools.web import register_web_tools
    from research_mcp.tools.academic import register_academic_tools
    from research_mcp.tools.video import register_video_tools
    from research_mcp.tools.github_docs import register_github_docs_tools
    from research_mcp.tools.document import register_document_tools
    from research_mcp.tools.wiki import register_wiki_tools
    from research_mcp.tools.index import register_index_tools

    register_web_tools(mcp)
    register_academic_tools(mcp)
    register_video_tools(mcp)
    register_github_docs_tools(mcp)
    register_document_tools(mcp)
    register_wiki_tools(mcp)
    register_index_tools(mcp)
