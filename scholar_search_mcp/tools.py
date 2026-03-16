"""MCP tool definitions."""

from mcp.types import Tool

from .models import TOOL_INPUT_MODELS

OPAQUE_CURSOR_CONTRACT = (
    "Treat pagination.nextCursor as an opaque server-issued token: pass it back "
    "exactly as returned, do not derive, edit, or fabricate it, and do not reuse "
    "it across a different tool or different query flow so pagination state "
    "integrity stays bound to the stream that produced it."
)

TOOL_DESCRIPTIONS = {
    "search_papers": (
        "Primary entry point for quick literature discovery: start here when "
        "quick topic exploration needs one strong first page fast. Best-effort "
        "paper search tries CORE → Semantic Scholar → "
        "SerpApi Google Scholar (opt-in, paid) → arXiv in order by default. "
        "Use preferredProvider to try one provider first, or providerOrder to "
        "override the broker chain for this call when source constraints matter. "
        "Provider names accepted by those arguments are core, semantic_scholar, "
        "arxiv, and either serpapi or serpapi_google_scholar. "
        "Optional filters: year, venue, publicationDateOrYear, "
        "fieldsOfStudy, publicationTypes, openAccessPdf, minCitationCount. "
        "Semantic Scholar-only filters still cause CORE and SerpApi to be "
        "skipped even if they appear in providerOrder. "
        "Returns a single page of results (no pagination). For large paginated "
        "retrieval use search_papers_bulk. "
        "brokerMetadata.providerUsed identifies which provider supplied the results, "
        "and brokerMetadata.attemptedProviders explains skips, failures, and fallbacks."
    ),
    "search_papers_core": (
        "Search papers using CORE only. Returns a single page of results with the "
        "same normalized response shape as search_papers, but does not fall back "
        "to other providers. Supported inputs are query, limit, and year."
    ),
    "search_papers_semantic_scholar": (
        "Search papers using Semantic Scholar only. Returns a single page of "
        "results with the same normalized response shape as search_papers, but "
        "does not fall back to other providers. This is the provider-specific "
        "tool that honors fields, year, venue, publicationDateOrYear, "
        "fieldsOfStudy, publicationTypes, openAccessPdf, and minCitationCount."
    ),
    "search_papers_serpapi": (
        "Search papers using SerpApi Google Scholar only. Requires "
        "SCHOLAR_SEARCH_ENABLE_SERPAPI=true and SERPAPI_API_KEY. Returns a "
        "single page of results with the same normalized response shape as "
        "search_papers, but does not fall back to other providers. Supported "
        "inputs are query, limit, and year."
    ),
    "search_papers_arxiv": (
        "Search papers using arXiv only. Returns a single page of results with "
        "the same normalized response shape as search_papers, but does not fall "
        "back to other providers. Supported inputs are query, limit, and year."
    ),
    "search_papers_bulk": (
        "Primary exhaustive retrieval tool for serious research, datasets, or "
        "multi-page collection. Paginated bulk paper search (Semantic Scholar) "
        "with advanced boolean query syntax. Supports sorting and returns up to "
        "1,000 papers per call, but the upstream bulk endpoint may ignore small "
        "limit values internally; this server truncates the returned data to the "
        "requested limit. Prefer search_papers or search_papers_semantic_scholar "
        "for small targeted pages. "
        "Example first call: {query: 'transformers', limit: 100}. "
        "Use cursor=pagination.nextCursor from the response to fetch the next "
        "page; hasMore signals when more results exist. "
        f"{OPAQUE_CURSOR_CONTRACT}"
    ),
    "search_papers_match": (
        "Known-item lookup for messy or partial titles. Find the single paper "
        "whose title best matches the query string."
    ),
    "paper_autocomplete": (
        "Return paper title completions for a partial query string."
    ),
    "get_paper_details": (
        "Known-item lookup when you already have an identifier. Get paper "
        "details from a DOI, ArXiv ID, Semantic Scholar ID, or URL."
    ),
    "get_paper_citations": (
        "Citation chasing outward: get papers that cite this paper (cited by). "
        "Use a Semantic Scholar paperId, DOI, or paper.canonicalId for expansion "
        "tools; provider-specific brokered ids such as raw CORE paperId/sourceId "
        "values are not portable. "
        "Pass cursor=pagination.nextCursor to continue; hasMore signals more pages. "
        f"{OPAQUE_CURSOR_CONTRACT}"
    ),
    "get_paper_references": (
        "Citation chasing backward: get the references this paper cites. "
        "Use a Semantic Scholar paperId, DOI, or paper.canonicalId for expansion "
        "tools; provider-specific brokered ids such as raw CORE paperId/sourceId "
        "values are not portable. "
        "Pass cursor=pagination.nextCursor to continue; hasMore signals more pages. "
        f"{OPAQUE_CURSOR_CONTRACT}"
    ),
    "get_paper_authors": (
        "Get authors of a paper so you can pivot from a paper into an author or "
        "collaboration workflow. Use a Semantic Scholar paperId, DOI, or "
        "paper.canonicalId for this Semantic Scholar expansion path; "
        "provider-specific brokered ids such as raw CORE paperId/sourceId values "
        "are not portable. "
        "Pass cursor=pagination.nextCursor to continue; hasMore signals more pages. "
        f"{OPAQUE_CURSOR_CONTRACT}"
    ),
    "get_author_info": (
        "Get author details for an author-centric workflow after search_authors "
        "or get_paper_authors. author_id must be a Semantic Scholar authorId from "
        "those tools."
    ),
    "get_author_papers": (
        "Author-centric workflow step: get papers by an author, including recent "
        "or filtered work. author_id must be a Semantic Scholar authorId from "
        "search_authors or get_paper_authors. "
        "Pass cursor=pagination.nextCursor to continue; hasMore signals more pages. "
        f"{OPAQUE_CURSOR_CONTRACT}"
    ),
    "search_authors": (
        "Primary author-search entry point. Search for authors by name before "
        "expanding to get_author_info or get_author_papers. Plain-text only: the "
        "server normalizes exact-name punctuation such as initials before calling "
        "Semantic Scholar. "
        "Pass cursor=pagination.nextCursor to continue; hasMore signals more pages. "
        f"{OPAQUE_CURSOR_CONTRACT}"
    ),
    "batch_get_authors": "Get details for multiple authors at once (up to 1,000).",
    "search_snippets": (
        "Special-purpose recovery tool for quote-like or phrase-based retrieval "
        "when title or keyword search is weak. Returns snippet text plus paper "
        "metadata and relevance score."
    ),
    "get_paper_recommendations": "Get similar paper recommendations for a paper.",
    "get_paper_recommendations_post": (
        "Get paper recommendations from positive and negative seed sets."
    ),
    "batch_get_papers": "Get details for multiple papers (up to 500).",
    "get_paper_citation_formats": (
        "Citation export step after discovery: get MLA, APA, BibTeX, and other "
        "formats for a Google Scholar paper. Requires "
        "SCHOLAR_SEARCH_ENABLE_SERPAPI=true and SERPAPI_API_KEY (paid SerpApi "
        "service, results cached 1 hour). "
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
