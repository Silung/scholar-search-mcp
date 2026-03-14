"""Dispatch helpers for MCP tool routing."""

from typing import Any, Callable, cast

from .models import TOOL_INPUT_MODELS, dump_jsonable
from .models.tools import SearchPapersArgs
from .search import search_papers_with_fallback

ToolArgBuilder = Callable[[dict[str, Any]], dict[str, Any]]


NON_SEARCH_TOOL_HANDLERS: dict[str, tuple[str, ToolArgBuilder]] = {
    "get_paper_details": (
        "get_paper_details",
        lambda arguments: {
            "paper_id": arguments["paper_id"],
            "fields": arguments.get("fields"),
        },
    ),
    "get_paper_citations": (
        "get_paper_citations",
        lambda arguments: {
            "paper_id": arguments["paper_id"],
            "limit": arguments.get("limit", 100),
            "fields": arguments.get("fields"),
        },
    ),
    "get_paper_references": (
        "get_paper_references",
        lambda arguments: {
            "paper_id": arguments["paper_id"],
            "limit": arguments.get("limit", 100),
            "fields": arguments.get("fields"),
        },
    ),
    "get_author_info": (
        "get_author_info",
        lambda arguments: {
            "author_id": arguments["author_id"],
            "fields": arguments.get("fields"),
        },
    ),
    "get_author_papers": (
        "get_author_papers",
        lambda arguments: {
            "author_id": arguments["author_id"],
            "limit": arguments.get("limit", 100),
            "fields": arguments.get("fields"),
        },
    ),
    "get_paper_recommendations": (
        "get_recommendations",
        lambda arguments: {
            "paper_id": arguments["paper_id"],
            "limit": arguments.get("limit", 10),
            "fields": arguments.get("fields"),
        },
    ),
    "batch_get_papers": (
        "batch_get_papers",
        lambda arguments: {
            "paper_ids": arguments["paper_ids"],
            "fields": arguments.get("fields"),
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
    result = await method(**build_args(validated_payload.model_dump()))
    return dump_jsonable(result)
