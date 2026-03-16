"""FastMCP-backed public server surface for Scholar Search."""

import json
import logging
from inspect import Parameter, Signature
from typing import Any, Literal, cast

from fastmcp import FastMCP
from fastmcp.server.middleware.timing import TimingMiddleware
from mcp.types import TextContent, Tool, ToolAnnotations
from pydantic import Field
from pydantic.fields import PydanticUndefined

from .clients import ArxivClient, CoreApiClient, SemanticScholarClient
from .clients.serpapi import SerpApiScholarClient
from .constants import (
    API_BASE_URL,
    ARXIV_API_BASE,
    ARXIV_NS,
    ATOM_NS,
    CORE_API_BASE,
    DEFAULT_AUTHOR_FIELDS,
    DEFAULT_PAPER_FIELDS,
    MAX_429_RETRIES,
    OPENSEARCH_NS,
    RECOMMENDATIONS_BASE_URL,
    SEMANTIC_SCHOLAR_MIN_INTERVAL,
)
from .dispatch import dispatch_tool
from .models import TOOL_INPUT_MODELS, dump_jsonable
from .parsing import _arxiv_id_from_url, _text
from .runtime import run_server
from .search import _core_response_to_merged, _merge_search_results
from .settings import AppSettings, _env_bool
from .tools import TOOL_DESCRIPTIONS
from .transport import asyncio, httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scholar-search-mcp")

SERVER_INSTRUCTIONS = """
Decision tree for tool selection:

1. QUICK DISCOVERY → search_papers (brokered, single page, returns brokerMetadata)
2. EXHAUSTIVE / MULTI-PAGE → search_papers_bulk
   (cursor-paginated, up to 1 000 returned/call)
3. KNOWN ITEM (messy title) → search_papers_match
4. KNOWN ITEM (DOI / arXiv / URL) → get_paper_details
5. CITATION EXPANSION → get_paper_citations (cited-by) or get_paper_references (refs)
6. AUTHOR PIVOT → search_authors → get_author_info → get_author_papers
7. PHRASE / QUOTE RECOVERY → search_snippets (last resort)

After search_papers: read brokerMetadata.nextStepHint for the recommended next move.
For Semantic Scholar expansion tools, prefer paper.canonicalId, DOI, or a
Semantic Scholar paperId rather than a provider-specific brokered id.
If search_papers_match returns no match, the item may be a dissertation,
software release, report, or other output outside the indexed paper surface.
For common-name author lookup, add affiliation, coauthor, venue, or topic clues
before expanding into get_author_info/get_author_papers.
To steer the broker: use preferredProvider (try-first) or providerOrder (full override).
Provider names: core, semantic_scholar, arxiv, serpapi / serpapi_google_scholar.
Provider-specific search inputs: search_papers_core, search_papers_serpapi, and
search_papers_arxiv only accept query/limit/year; search_papers_semantic_scholar
supports the wider Semantic Scholar filter set.
Continuation rule: search_papers_bulk is the closest continuation path only for
Semantic Scholar-style retrieval; from CORE, arXiv, or SerpApi results it is a
Semantic Scholar pivot rather than another page from the same provider.
For small targeted pages, prefer search_papers or search_papers_semantic_scholar;
Semantic Scholar's bulk endpoint may ignore small limits internally.

Pagination rule: treat pagination.nextCursor as opaque — pass it back exactly as
returned, do not derive, edit, or fabricate it, and do not reuse it across a
different tool or query flow.
""".strip()

AGENT_WORKFLOW_GUIDE = """
# Scholar Search agent workflow guide

## Quick decision tree

- **Quick literature discovery**: `search_papers` → inspect
  `brokerMetadata.nextStepHint` to decide whether to broaden, narrow,
  paginate, or pivot.
- **Exhaustive / multi-page retrieval**: `search_papers_bulk` with cursor loop until
  `pagination.hasMore` is false.
- **Small targeted Semantic Scholar page**: `search_papers_semantic_scholar` (or
  `search_papers` if brokered discovery is fine) instead of bulk retrieval.
- **Known-item lookup (messy title)**: `search_papers_match`
- **Known-item lookup (DOI / arXiv / URL / S2 ID)**: `get_paper_details`
- **Citation chasing (cited-by expansion)**: `get_paper_citations`
- **Citation chasing (backward references)**: `get_paper_references`
- **Author-centric workflows**: `search_authors` → `get_author_info` →
  `get_author_papers`; pivot to `get_paper_authors` if starting from a paper.
- **Common-name author disambiguation**: add affiliation, coauthor, venue, or
  topic clues to `search_authors`, then confirm identity with
  `get_author_info`/`get_author_papers`.
- **Cross-provider ID portability**: for Semantic Scholar expansion tools prefer
  `paper.canonicalId`, DOI, or a Semantic Scholar `paperId`; brokered provider
  IDs such as raw CORE `paperId`/`sourceId` are not portable.
- **Outside-paper outputs**: dissertations, software releases, reports, and
  other grey literature may fall outside the indexed paper surface even when a
  title is real; treat a structured no-match from `search_papers_match` as a
  signal to verify externally.
- **Quote or snippet validation**: `search_snippets` — special-purpose recovery
  tool only when title/keyword search is weak; provider 4xx/5xx errors degrade
  to empty results with retry guidance.
- **Citation export**: `get_paper_citation_formats` — pass
  `result_id=paper.scholarResultId` (not `paper.sourceId`) from any
  `serpapi_google_scholar` result to get MLA, APA, BibTeX, etc.

## Provider steering

Set `preferredProvider` on `search_papers` to try one provider first while keeping
the fallback chain. Set `providerOrder` to override the full broker chain for one
call. Use `search_papers_core`, `search_papers_semantic_scholar`,
`search_papers_serpapi`, or `search_papers_arxiv` for single-source searches.

## Provider-specific tool contracts

- `search_papers_core`, `search_papers_serpapi`, and `search_papers_arxiv`
    expose only `query`, `limit`, and `year`.
- `search_papers_semantic_scholar` exposes the wider Semantic Scholar-compatible
    filter set.

## Continuation vs pivot

- `search_papers_bulk` is the closest continuation path when the task is already
    aligned with Semantic Scholar retrieval semantics.
- If `search_papers` returned CORE, arXiv, or SerpApi results, `search_papers_bulk`
    is a Semantic Scholar pivot, not another page from the same provider.
- Venue-filtered Semantic Scholar searches can also broaden when moved to bulk
    retrieval.
- For small targeted pages, prefer `search_papers` or
    `search_papers_semantic_scholar`; the upstream bulk endpoint may ignore small
    `limit` values internally.

## Pagination contract

For every paginated tool: treat `pagination.nextCursor` as opaque, pass it back
exactly as returned, and do not derive, edit, fabricate, or cross-reuse it.
""".strip()

__all__ = [
    "API_BASE_URL",
    "ARXIV_API_BASE",
    "ARXIV_NS",
    "ATOM_NS",
    "CORE_API_BASE",
    "DEFAULT_AUTHOR_FIELDS",
    "DEFAULT_PAPER_FIELDS",
    "MAX_429_RETRIES",
    "OPENSEARCH_NS",
    "RECOMMENDATIONS_BASE_URL",
    "SEMANTIC_SCHOLAR_MIN_INTERVAL",
    "SemanticScholarClient",
    "CoreApiClient",
    "ArxivClient",
    "SerpApiScholarClient",
    "_arxiv_id_from_url",
    "_text",
    "_core_response_to_merged",
    "_merge_search_results",
    "_env_bool",
    "asyncio",
    "httpx",
    "app",
    "http_app",
    "build_http_app",
    "settings",
    "api_key",
    "core_api_key",
    "serpapi_api_key",
    "enable_core",
    "enable_semantic_scholar",
    "enable_arxiv",
    "enable_serpapi",
    "client",
    "core_client",
    "arxiv_client",
    "serpapi_client",
    "list_tools",
    "call_tool",
    "main",
]


def _format_tool_display_name(name: str) -> str:
    return name.replace("_", " ").title()


def _tool_tags(name: str) -> set[str]:
    provider_tags = {
        "search_papers": {"search", "brokered"},
        "search_papers_core": {"search", "provider-specific", "provider:core"},
        "search_papers_semantic_scholar": {
            "search",
            "provider-specific",
            "provider:semantic_scholar",
        },
        "search_papers_serpapi": {
            "search",
            "provider-specific",
            "provider:serpapi_google_scholar",
        },
        "search_papers_arxiv": {"search", "provider-specific", "provider:arxiv"},
    }
    if name in provider_tags:
        return provider_tags[name]
    if name.startswith("search_"):
        return {"search"}
    if name.startswith("get_paper_"):
        return {"paper"}
    if name.startswith("get_author_") or name == "search_authors":
        return {"author"}
    if name.startswith("batch_"):
        return {"batch"}
    return {"scholar-search"}


def _parameter_name(field_name: str, alias: str | None) -> str:
    return alias or field_name


def _parameter_default(model_field: Any) -> Any:
    if model_field.is_required():
        return Parameter.empty
    default = model_field.default
    if default is PydanticUndefined:
        default = None
    return Field(default=default, description=model_field.description)


def _build_signature(model: Any) -> tuple[Signature, dict[str, Any]]:
    parameters: list[Parameter] = []
    annotations: dict[str, Any] = {"return": dict[str, Any]}
    for field_name, model_field in model.model_fields.items():
        parameter_name = _parameter_name(field_name, model_field.alias)
        annotations[parameter_name] = model_field.annotation
        parameters.append(
            Parameter(
                parameter_name,
                Parameter.POSITIONAL_OR_KEYWORD,
                annotation=model_field.annotation,
                default=_parameter_default(model_field),
            )
        )
    return Signature(parameters=parameters), annotations


def _register_tool(tool_name: str) -> None:
    signature, annotations = _build_signature(TOOL_INPUT_MODELS[tool_name])

    async def _tool_impl(**kwargs: Any) -> dict[str, Any]:
        return await _execute_tool(tool_name, kwargs)

    _tool_impl.__name__ = tool_name
    _tool_impl.__doc__ = TOOL_DESCRIPTIONS[tool_name]
    setattr(_tool_impl, "__signature__", signature)
    _tool_impl.__annotations__ = annotations

    app.tool(
        name=tool_name,
        title=_format_tool_display_name(tool_name),
        description=TOOL_DESCRIPTIONS[tool_name],
        tags=_tool_tags(tool_name),
        annotations=ToolAnnotations(
            title=_format_tool_display_name(tool_name),
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )(_tool_impl)


async def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return await dispatch_tool(
        name,
        arguments,
        client=client,
        core_client=core_client,
        arxiv_client=arxiv_client,
        enable_core=enable_core,
        enable_semantic_scholar=enable_semantic_scholar,
        enable_arxiv=enable_arxiv,
        serpapi_client=serpapi_client,
        enable_serpapi=enable_serpapi,
        provider_order=provider_order,
    )


settings = AppSettings.from_env()
api_key = settings.semantic_scholar_api_key
core_api_key = settings.core_api_key
serpapi_api_key = settings.serpapi_api_key
enable_core = settings.enable_core
enable_semantic_scholar = settings.enable_semantic_scholar
enable_arxiv = settings.enable_arxiv
enable_serpapi = settings.enable_serpapi
provider_order = list(settings.provider_order)
client = SemanticScholarClient(api_key=api_key)
core_client = CoreApiClient(api_key=core_api_key)
arxiv_client = ArxivClient()
serpapi_client = SerpApiScholarClient(api_key=serpapi_api_key)

app = FastMCP(
    "scholar-search",
    instructions=SERVER_INSTRUCTIONS,
    strict_input_validation=True,
)
app.add_middleware(TimingMiddleware(logger=logger))

for _tool_name in TOOL_INPUT_MODELS:
    _register_tool(_tool_name)


@app.resource(
    "guide://scholar-search/agent-workflows",
    title="Scholar Search agent workflows",
    description="How to choose the right scholar-search tools and pagination flow.",
)
def agent_workflows() -> str:
    """Return a compact workflow guide for agents."""
    return AGENT_WORKFLOW_GUIDE


@app.prompt(
    name="plan_scholar_search",
    title="Plan Scholar Search",
    description="Generate a tool-first plan for a literature search task.",
)
def plan_scholar_search(
    topic: str,
    goal: str = "find relevant papers, follow citations, and summarize next steps",
) -> str:
    """Create a reusable research workflow prompt for clients."""
    return (
        f"You are planning a scholar-search workflow about '{topic}'. Goal: {goal}. "
        "Start with search_papers for quick literature discovery, then read "
        "brokerMetadata.nextStepHint to decide whether to broaden, narrow, paginate, "
        "pivot providers, or pivot into authors. "
        "Treat search_papers_bulk as the closest continuation path only when the "
        "workflow is already aligned with Semantic Scholar retrieval semantics; if "
        "results came from CORE, arXiv, or SerpApi, bulk retrieval is a Semantic "
        "Scholar pivot rather than another page from the same provider. "
        "If the task is exhaustive retrieval, first N results, or multi-page "
        "collection, use search_papers_bulk. For small targeted pages, prefer "
        "search_papers or search_papers_semantic_scholar because the upstream "
        "bulk endpoint may ignore small limit values internally. "
        "If the task is known-item lookup, use search_papers_match for messy titles "
        "and get_paper_details for DOI, arXiv ID, URL, or canonical IDs. Treat a "
        "structured no-match from search_papers_match as a hint that the item may "
        "be a dissertation, software release, report, or other output outside the "
        "indexed paper surface. "
        "If the task starts from a known paper, use get_paper_citations for cited-by "
        "expansion and get_paper_references for backward references, and explain "
        "that direction clearly. "
        "For author-centric workflows use search_authors, get_author_info, and "
        "get_author_papers. For common names, add affiliation, coauthor, venue, "
        "or topic clues before confirming the best candidate. For Semantic "
        "Scholar expansion tools prefer "
        "paper.canonicalId, DOI, or a Semantic Scholar paperId rather than a "
        "provider-specific brokered id. "
        "Use search_snippets only as a special-purpose recovery tool when quote or "
        "phrase search is needed and title/keyword search is weak; if the provider "
        "rejects that query, expect an empty degraded response rather than a raw "
        "4xx/5xx. "
        "Use preferredProvider/providerOrder or provider-specific search_papers_* "
        "tools only when source choice matters. Remember that search_papers_core, "
        "search_papers_serpapi, and search_papers_arxiv only support query, limit, "
        "and year, while search_papers_semantic_scholar supports the wider filter set. "
        "Treat pagination.nextCursor as opaque: reuse it exactly as returned, do "
        "not edit or fabricate it, and keep it scoped to the tool/query flow that "
        "produced it."
    )


http_app_transport = cast(
    Literal["http", "streamable-http", "sse"],
    settings.transport if settings.transport != "stdio" else "streamable-http",
)


def build_http_app(
    *,
    path: str | None = None,
    transport: Literal["http", "streamable-http", "sse"] | None = None,
    middleware: list[Any] | None = None,
) -> Any:
    """Build an ASGI app for local/dev HTTP use or custom deployment hardening."""
    return app.http_app(
        path=path or settings.http_path,
        transport=transport or http_app_transport,
        middleware=middleware,
    )


http_app = build_http_app()


async def list_tools() -> list[Tool]:
    """Compatibility helper returning the registered tool schemas."""
    return [
        cast(Tool, tool.to_mcp_tool() if hasattr(tool, "to_mcp_tool") else tool)
        for tool in await app.list_tools(run_middleware=False)
    ]


async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Compatibility helper preserving the historic JSON-in-text test contract."""
    result = await _execute_tool(name, arguments)
    return [
        TextContent(
            type="text",
            text=json.dumps(dump_jsonable(result), ensure_ascii=False, indent=2),
        )
    ]


def main() -> None:
    """Run the MCP server."""
    run_server(app=app, logger=logger, settings=settings)


if __name__ == "__main__":
    main()
