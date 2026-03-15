"""Dispatch helpers for MCP tool routing."""

from typing import Any, Callable, cast

from .clients.serpapi import SerpApiKeyMissingError
from .models import TOOL_INPUT_MODELS, CitationFormatsResponse, dump_jsonable
from .models.common import CitationFormat, ExportLink
from .models.tools import (
    GetCitationFormatsArgs,
    SearchPapersArgs,
    SearchPapersBaseArgs,
    SearchProvider,
)
from .search import search_papers_with_fallback
from .utils.cursor import (
    OFFSET_TOOLS,
    PROVIDER,
    SUPPORTED_VERSIONS,
    compute_context_hash,
    cursor_from_offset,
    decode_cursor,
    is_legacy_offset,
)

ToolArgBuilder = Callable[[dict[str, Any]], dict[str, Any]]
CURSOR_REUSE_HINT = (
    "Pass pagination.nextCursor back exactly as returned. Do not derive, edit, "
    "or fabricate cursors, and do not reuse them across a different tool or "
    "different query context."
)


def _cursor_to_offset(
    cursor: str | None,
    tool: str | None = None,
    context_hash: str | None = None,
) -> int | None:
    """Decode an opaque pagination cursor to an integer offset.

    Accepts both structured server-issued cursors (URL-safe base64 JSON) and
    legacy plain integer strings for backward compatibility.

    Returns ``None`` when *cursor* is ``None`` (start from the beginning).

    When *tool* is provided, structured cursors are validated to ensure they
    were issued by the same tool.  When *context_hash* is also provided, the
    cursor's embedded hash is compared against the current request's context,
    so a cursor from a different query on the same tool is rejected.

    In production all dispatch handlers pass *tool* and *context_hash*
    explicitly.  Passing ``tool=None`` skips cross-tool validation; this is
    intentional only for the ``cursor=None`` early-return path.

    Raises ``ValueError`` for stale, mis-typed, corrupted, cross-tool, or
    cross-query cursors, unsupported versions, unknown providers, and negative
    integer offsets.
    """
    if cursor is None:
        return None
    if is_legacy_offset(cursor):
        offset = int(cursor)
        if offset < 0:
            raise ValueError(
                f"Invalid pagination cursor {cursor!r}: offset must be non-negative. "
                "code=INVALID_CURSOR. "
                f"{CURSOR_REUSE_HINT} Restart the request without a cursor."
            )
        return offset
    # Structured cursor: decode and validate
    try:
        state = decode_cursor(cursor)
    except ValueError:
        raise ValueError(
            f"Invalid pagination cursor {cursor!r}: cannot be decoded. "
            "code=INVALID_CURSOR. "
            f"{CURSOR_REUSE_HINT} Restart the request without a cursor."
        )
    if state.provider != PROVIDER:
        raise ValueError(
            f"Invalid pagination cursor: cursor provider {state.provider!r} does not "
            f"match expected provider {PROVIDER!r}. "
            "code=INVALID_CURSOR. "
            f"{CURSOR_REUSE_HINT} Restart the request without a cursor."
        )
    if state.version not in SUPPORTED_VERSIONS:
        raise ValueError(
            f"Invalid pagination cursor: cursor version {state.version} is not "
            f"supported (supported: {sorted(SUPPORTED_VERSIONS)}). "
            "code=INVALID_CURSOR. "
            f"{CURSOR_REUSE_HINT} Restart the request without a cursor."
        )
    if tool is not None and state.tool != tool:
        raise ValueError(
            f"Invalid pagination cursor: cursor was issued by tool {state.tool!r} "
            f"but is being used with tool {tool!r}. "
            "code=INVALID_CURSOR. "
            f"{CURSOR_REUSE_HINT} Restart the request without a cursor."
        )
    if (
        context_hash is not None
        and state.context_hash is not None
        and state.context_hash != context_hash
    ):
        raise ValueError(
            "Invalid pagination cursor: cursor was issued for a different query "
            "context and cannot be reused here. "
            "code=INVALID_CURSOR. "
            f"{CURSOR_REUSE_HINT} Restart the request without a cursor."
        )
    return state.offset


def _encode_next_cursor(
    result: dict[str, Any],
    tool: str,
    context_hash: str | None = None,
) -> dict[str, Any]:
    """Re-encode a plain integer ``nextCursor`` in *result* as a structured cursor.

    Operates on the serialized dict returned by ``dump_jsonable``.  The
    ``pagination`` key is present on all offset-backed tool responses.

    The *context_hash* is embedded into the new cursor so that future requests
    can validate that the cursor belongs to the same query stream.

    If ``pagination.nextCursor`` is already a structured (non-integer) cursor or
    is ``None``, the result is returned unchanged.
    """
    pagination = result.get("pagination")
    if not isinstance(pagination, dict):
        return result
    raw_cursor = pagination.get("nextCursor")
    if raw_cursor is None:
        return result
    if is_legacy_offset(raw_cursor):
        pagination["nextCursor"] = cursor_from_offset(
            tool, int(raw_cursor), context_hash=context_hash
        )
    return result


NON_SEARCH_TOOL_HANDLERS: dict[str, tuple[str, ToolArgBuilder]] = {
    "search_papers_bulk": (
        "search_papers_bulk",
        lambda a: {
            "query": a["query"],
            "fields": a.get("fields"),
            "token": a.get("cursor"),
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
            "offset": _cursor_to_offset(
                a.get("cursor"),
                "get_paper_citations",
                context_hash=compute_context_hash("get_paper_citations", a),
            ),
        },
    ),
    "get_paper_references": (
        "get_paper_references",
        lambda a: {
            "paper_id": a["paper_id"],
            "limit": a.get("limit", 100),
            "fields": a.get("fields"),
            "offset": _cursor_to_offset(
                a.get("cursor"),
                "get_paper_references",
                context_hash=compute_context_hash("get_paper_references", a),
            ),
        },
    ),
    "get_paper_authors": (
        "get_paper_authors",
        lambda a: {
            "paper_id": a["paper_id"],
            "limit": a.get("limit", 100),
            "fields": a.get("fields"),
            "offset": _cursor_to_offset(
                a.get("cursor"),
                "get_paper_authors",
                context_hash=compute_context_hash("get_paper_authors", a),
            ),
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
            "offset": _cursor_to_offset(
                a.get("cursor"),
                "get_author_papers",
                context_hash=compute_context_hash("get_author_papers", a),
            ),
            "publication_date_or_year": a.get("publication_date_or_year"),
        },
    ),
    "search_authors": (
        "search_authors",
        lambda a: {
            "query": a["query"],
            "limit": a.get("limit", 10),
            "fields": a.get("fields"),
            "offset": _cursor_to_offset(
                a.get("cursor"),
                "search_authors",
                context_hash=compute_context_hash("search_authors", a),
            ),
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

PROVIDER_SEARCH_TOOLS: dict[str, SearchProvider] = {
    "search_papers_core": "core",
    "search_papers_semantic_scholar": "semantic_scholar",
    "search_papers_serpapi": "serpapi_google_scholar",
    "search_papers_arxiv": "arxiv",
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
    serpapi_client: Any = None,
    enable_serpapi: bool = False,
    provider_order: list[SearchProvider] | None = None,
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
            publication_date_or_year=validated_arguments.publication_date_or_year,
            fields_of_study=validated_arguments.fields_of_study,
            publication_types=validated_arguments.publication_types,
            open_access_pdf=validated_arguments.open_access_pdf,
            min_citation_count=validated_arguments.min_citation_count,
            enable_core=enable_core,
            enable_semantic_scholar=enable_semantic_scholar,
            enable_arxiv=enable_arxiv,
            enable_serpapi=enable_serpapi,
            preferred_provider=validated_arguments.preferred_provider,
            provider_order=validated_arguments.provider_order or provider_order,
            core_client=core_client,
            semantic_client=client,
            arxiv_client=arxiv_client,
            serpapi_client=serpapi_client,
        )

    if name in PROVIDER_SEARCH_TOOLS:
        provider_arguments = cast(
            SearchPapersBaseArgs,
            TOOL_INPUT_MODELS[name].model_validate(arguments),
        )
        return await search_papers_with_fallback(
            query=provider_arguments.query,
            limit=provider_arguments.limit,
            year=provider_arguments.year,
            fields=provider_arguments.fields,
            venue=provider_arguments.venue,
            publication_date_or_year=provider_arguments.publication_date_or_year,
            fields_of_study=provider_arguments.fields_of_study,
            publication_types=provider_arguments.publication_types,
            open_access_pdf=provider_arguments.open_access_pdf,
            min_citation_count=provider_arguments.min_citation_count,
            enable_core=enable_core,
            enable_semantic_scholar=enable_semantic_scholar,
            enable_arxiv=enable_arxiv,
            enable_serpapi=enable_serpapi,
            provider_order=[PROVIDER_SEARCH_TOOLS[name]],
            core_client=core_client,
            semantic_client=client,
            arxiv_client=arxiv_client,
            serpapi_client=serpapi_client,
        )

    if name == "get_paper_citation_formats":
        validated_cf = cast(
            GetCitationFormatsArgs,
            TOOL_INPUT_MODELS[name].model_validate(arguments),
        )
        if not enable_serpapi:
            raise ValueError(
                "get_paper_citation_formats requires SerpApi, which is not enabled. "
                "Set SCHOLAR_SEARCH_ENABLE_SERPAPI=true and provide SERPAPI_API_KEY "
                "to use this tool. SerpApi is a paid service — see "
                "https://serpapi.com for details."
            )
        if serpapi_client is None:
            raise ValueError(
                "SerpApi client is not available. "
                "Set SCHOLAR_SEARCH_ENABLE_SERPAPI=true and SERPAPI_API_KEY."
            )
        try:
            raw = await serpapi_client.get_citation_formats(
                result_id=validated_cf.result_id,
            )
        except SerpApiKeyMissingError:
            raise
        raw_citations = raw.get("citations") or []
        raw_links = raw.get("links") or []
        response = CitationFormatsResponse(
            result_id=validated_cf.result_id,
            citations=[
                CitationFormat(
                    title=str(c.get("title") or ""),
                    snippet=str(c.get("snippet") or ""),
                )
                for c in raw_citations
                if isinstance(c, dict)
            ],
            export_links=[
                ExportLink(
                    name=str(lnk.get("name") or ""),
                    link=str(lnk.get("link") or ""),
                )
                for lnk in raw_links
                if isinstance(lnk, dict)
            ],
        )
        return dump_jsonable(response)

    try:
        method_name, build_args = NON_SEARCH_TOOL_HANDLERS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown tool: {name}") from exc

    validated_payload = TOOL_INPUT_MODELS[name].model_validate(arguments)
    args_dict = validated_payload.model_dump(by_alias=False)
    ctx_hash = compute_context_hash(name, args_dict) if name in OFFSET_TOOLS else None
    method = getattr(client, method_name)
    result = await method(**build_args(args_dict))
    serialized = dump_jsonable(result)
    if name in OFFSET_TOOLS:
        serialized = _encode_next_cursor(serialized, name, context_hash=ctx_hash)
    return serialized
