"""MCP tool definitions."""

from mcp.types import Tool

from .models import TOOL_INPUT_MODELS

TOOL_DESCRIPTIONS = {
    "search_papers": (
        "Search academic papers by keyword. Optional filters: year, venue."
    ),
    "get_paper_details": (
        "Get paper details. Supports DOI, ArXiv ID, Semantic Scholar ID, or URL."
    ),
    "get_paper_citations": "Get list of papers that cite this paper.",
    "get_paper_references": "Get list of references of this paper.",
    "get_author_info": "Get author details.",
    "get_author_papers": "Get papers by author.",
    "get_paper_recommendations": "Get similar paper recommendations for a paper.",
    "batch_get_papers": "Get details for multiple papers (up to 500).",
}


def get_tool_definitions() -> list[Tool]:
    """Return the MCP tool schema exposed by the server."""
    return [
        Tool(
            name=name,
            description=TOOL_DESCRIPTIONS[name],
            inputSchema=model.model_json_schema(),
        )
        for name, model in TOOL_INPUT_MODELS.items()
    ]
