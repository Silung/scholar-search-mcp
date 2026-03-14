"""MCP tool definitions."""

from mcp.types import Tool

from .models import TOOL_INPUT_MODELS

TOOL_DESCRIPTIONS = {
    "search_papers": (
        "Search academic papers by keyword. Optional filters: year, venue, "
        "offset, publicationDateOrYear, fieldsOfStudy, publicationTypes, "
        "openAccessPdf, minCitationCount."
    ),
    "search_papers_bulk": (
        "Bulk paper search using advanced boolean query syntax. Supports token-"
        "based pagination, sorting, and up to 1,000 papers per call."
    ),
    "search_papers_match": (
        "Find the single paper whose title best matches the query string."
    ),
    "paper_autocomplete": (
        "Return paper title completions for a partial query string. Designed for "
        "typeahead or interactive search UI."
    ),
    "get_paper_details": (
        "Get paper details. Supports DOI, ArXiv ID, Semantic Scholar ID, or URL."
    ),
    "get_paper_citations": "Get list of papers that cite this paper.",
    "get_paper_references": "Get list of references of this paper.",
    "get_paper_authors": "Get the list of authors for a given paper.",
    "get_author_info": "Get author details.",
    "get_author_papers": "Get papers by author.",
    "search_authors": "Search for authors by name.",
    "batch_get_authors": "Get details for multiple authors at once (up to 1,000).",
    "search_snippets": (
        "Search for matching text snippets across papers. Useful for quote-like "
        "retrieval. Returns snippet text plus paper metadata and relevance score."
    ),
    "get_paper_recommendations": "Get similar paper recommendations for a paper.",
    "get_paper_recommendations_post": (
        "Get paper recommendations from positive and negative seed sets. More "
        "flexible than the single-seed GET route."
    ),
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
