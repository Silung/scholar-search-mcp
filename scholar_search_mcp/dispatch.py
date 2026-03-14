"""Dispatch helpers for MCP tool routing."""

from typing import Any, Callable, cast

from .models import TOOL_INPUT_MODELS, dump_jsonable
from .models.tools import SearchPapersArgs
from .search import search_papers_with_fallback

ToolArgBuilder = Callable[[dict[str, Any]], dict[str, Any]]


NON_SEARCH_TOOL_HANDLERS: dict[str, tuple[str, ToolArgBuilder]] = {
    "search_papers_bulk": (
        "search_papers_bulk",
        lambda a: {
            "query": a["query"],
            "fields": a.get("fields"),
            "token": a.get("token"),
            "sort": a.get("sort"),
            "limit": a.get("limit", 100),
            "year": a.get("year"),
            "publication_date_or_year": a.get("publication_date_or_year"),
            "fields_of_study": a.get("fields_of_study"),
            "publication_types": a.get("publication_types"),
            "open_access_pdf": a.get("open_access_pdf"),
            "min_citation_count": a.get("min_citation_count"),
        },
    ),
    "search_papers_match": (
        "search_papers_match",
        lambda a: {
            "query": a["query"],
            "fields": a.get("fields"),
        },
    ),
    "paper_autocomplete": (
        "paper_autocomplete",
        lambda a: {"query": a["query"]},
    ),
    "get_paper_details": (
        "get_paper_details",
        lambda a: {
            "paper_id": a["paper_id"],
            "fields": a.get("fields"),
        },
    ),
    "get_paper_citations": (
        "get_paper_citations",
        lambda a: {
            "paper_id": a["paper_id"],
            "limit": a.get("limit", 100),
            "fields": a.get("fields"),
            "offset": a.get("offset"),
        },
    ),
    "get_paper_references": (
        "get_paper_references",
        lambda a: {
            "paper_id": a["paper_id"],
            "limit": a.get("limit", 100),
            "fields": a.get("fields"),
            "offset": a.get("offset"),
        },
    ),
    "get_paper_authors": (
        "get_paper_authors",
        lambda a: {
            "paper_id": a["paper_id"],
            "limit": a.get("limit", 100),
            "fields": a.get("fields"),
            "offset": a.get("offset"),
        },
    ),
    "get_author_info": (
        "get_author_info",
        lambda a: {
            "author_id": a["author_id"],
            "fields": a.get("fields"),
        },
    ),
    "get_author_papers": (
        "get_author_papers",
        lambda a: {
            "author_id": a["author_id"],
            "limit": a.get("limit", 100),
            "fields": a.get("fields"),
            "offset": a.get("offset"),
            "publication_date_or_year": a.get("publication_date_or_year"),
        },
    ),
    "search_authors": (
        "search_authors",
        lambda a: {
            "query": a["query"],
            "limit": a.get("limit", 10),
            "fields": a.get("fields"),
            "offset": a.get("offset"),
        },
    ),
    "batch_get_authors": (
        "batch_get_authors",
        lambda a: {
            "author_ids": a["author_ids"],
            "fields": a.get("fields"),
        },
    ),
    "search_snippets": (
        "search_snippets",
        lambda a: {
            "query": a["query"],
            "limit": a.get("limit", 10),
            "fields": a.get("fields"),
            "year": a.get("year"),
            "publication_date_or_year": a.get("publication_date_or_year"),
            "fields_of_study": a.get("fields_of_study"),
            "min_citation_count": a.get("min_citation_count"),
            "venue": a.get("venue"),
        },
    ),
    "get_paper_recommendations": (
        "get_recommendations",
        lambda a: {
            "paper_id": a["paper_id"],
            "limit": a.get("limit", 10),
            "fields": a.get("fields"),
        },
    ),
    "get_paper_recommendations_post": (
        "get_recommendations_post",
        lambda a: {
            "positive_paper_ids": a["positive_paper_ids"],
            "negative_paper_ids": a.get("negative_paper_ids"),
            "limit": a.get("limit", 10),
            "fields": a.get("fields"),
        },
    ),
    "batch_get_papers": (
        "batch_get_papers",
        lambda a: {
            "paper_ids": a["paper_ids"],
            "fields": a.get("fields"),
        },
    ),
}


async def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    client: Any,
    core_client: Any,
    arxiv_client: Any,
    enable_core: bool,
    enable_semantic_scholar: bool,
    enable_arxiv: bool,
) -> dict[str, Any]:
    """Dispatch one MCP tool call to the correct backend implementation."""
    if name == "search_papers":
        validated_arguments = cast(
            SearchPapersArgs,
            TOOL_INPUT_MODELS[name].model_validate(arguments),
        )
        return await search_papers_with_fallback(
            query=validated_arguments.query,
            limit=validated_arguments.limit,
            year=validated_arguments.year,
            fields=validated_arguments.fields,
            venue=validated_arguments.venue,
            offset=validated_arguments.offset,
            publication_date_or_year=validated_arguments.publication_date_or_year,
            fields_of_study=validated_arguments.fields_of_study,
            publication_types=validated_arguments.publication_types,
            open_access_pdf=validated_arguments.open_access_pdf,
            min_citation_count=validated_arguments.min_citation_count,
            enable_core=enable_core,
            enable_semantic_scholar=enable_semantic_scholar,
            enable_arxiv=enable_arxiv,
            core_client=core_client,
            semantic_client=client,
            arxiv_client=arxiv_client,
        )

    try:
        method_name, build_args = NON_SEARCH_TOOL_HANDLERS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown tool: {name}") from exc

    validated_payload = TOOL_INPUT_MODELS[name].model_validate(arguments)
    method = getattr(client, method_name)
    result = await method(**build_args(validated_payload.model_dump(by_alias=False)))
    return dump_jsonable(result)
