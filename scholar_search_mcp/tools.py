"""MCP tool definitions."""

from mcp.types import Tool

from .models import TOOL_INPUT_MODELS

TOOL_DESCRIPTIONS = {
    "search_papers": (
        "Best-effort paper search that tries CORE → Semantic Scholar → "
        "SerpApi Google Scholar (opt-in, paid) → arXiv in order. "
        "Optional filters: year, venue, publicationDateOrYear, "
        "fieldsOfStudy, publicationTypes, openAccessPdf, minCitationCount. "
        "Returns a single page of results (no pagination). For large paginated "
        "retrieval use search_papers_bulk. "
        "brokerMetadata.providerUsed identifies which provider supplied the results, "
        "and brokerMetadata.attemptedProviders explains skips, failures, and fallbacks."
    ),
    "search_papers_bulk": (
        "Paginated bulk paper search (Semantic Scholar) with advanced boolean "
        "query syntax. Supports sorting and up to 1,000 papers per call. "
        "Example first call: {query: 'transformers', limit: 100}. "
        "Use cursor=pagination.nextCursor from the response to fetch the next "
        "page; hasMore signals when more results exist."
    ),
    "search_papers_match": (
        "Find the single paper whose title best matches the query string."
    ),
    "paper_autocomplete": (
        "Return paper title completions for a partial query string."
    ),
    "get_paper_details": (
        "Get paper details. Supports DOI, ArXiv ID, Semantic Scholar ID, or URL."
    ),
    "get_paper_citations": (
        "Get papers that cite this paper. "
        "Pass cursor=pagination.nextCursor to continue; hasMore signals more pages."
    ),
    "get_paper_references": (
        "Get references of this paper. "
        "Pass cursor=pagination.nextCursor to continue; hasMore signals more pages."
    ),
    "get_paper_authors": (
        "Get authors of a paper. "
        "Pass cursor=pagination.nextCursor to continue; hasMore signals more pages."
    ),
    "get_author_info": "Get author details.",
    "get_author_papers": (
        "Get papers by an author. "
        "Pass cursor=pagination.nextCursor to continue; hasMore signals more pages."
    ),
    "search_authors": (
        "Search for authors by name. "
        "Pass cursor=pagination.nextCursor to continue; hasMore signals more pages."
    ),
    "batch_get_authors": "Get details for multiple authors at once (up to 1,000).",
    "search_snippets": (
        "Search for matching text snippets across papers. Useful for quote-like "
        "retrieval. Returns snippet text plus paper metadata and relevance score."
    ),
    "get_paper_recommendations": "Get similar paper recommendations for a paper.",
    "get_paper_recommendations_post": (
        "Get paper recommendations from positive and negative seed sets."
    ),
    "batch_get_papers": "Get details for multiple papers (up to 500).",
    "get_paper_citation_formats": (
        "Get citation export formats (MLA, APA, BibTeX, etc.) for a Google Scholar "
        "paper. Requires SCHOLAR_SEARCH_ENABLE_SERPAPI=true and SERPAPI_API_KEY "
        "(paid SerpApi service, results cached 1 hour). "
        "Pass result_id=paper.scholarResultId (NOT paper.sourceId) from a "
        "serpapi_google_scholar search_papers result. "
        "paper.scholarResultId is the raw Scholar result_id; paper.sourceId may "
        "be a cluster_id or cites_id, which this tool cannot use. "
        "If paper.scholarResultId is absent, the paper cannot be used with this "
        "tool. "
        "Returns text citation strings and structured export links (BibTeX, "
        "EndNote, RefMan, RefWorks). "
        "Not paginated — single response per paper."
    ),
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
