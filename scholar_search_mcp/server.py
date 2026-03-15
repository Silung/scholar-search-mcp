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
Use `search_papers` for a quick, brokered single page of candidate papers.
Use `search_papers_bulk` when you need exhaustive retrieval or pagination.
For every paginated tool, pass `pagination.nextCursor` back as `cursor`
exactly as returned.
Inspect `brokerMetadata` on `search_papers` responses to see which
providers were attempted, which one produced the results, and whether
Semantic Scholar-only filters narrowed the route.
""".strip()

AGENT_WORKFLOW_GUIDE = """
# Scholar Search agent workflow guide

- Start with `search_papers` when you want one best-effort page quickly.
- If you need pagination or exhaustive retrieval, switch to `search_papers_bulk`.
- Follow `brokerMetadata.providerUsed` to understand where results came from.
- Follow `brokerMetadata.attemptedProviders` to see skipped, failed, or empty providers.
- For paginated tools, treat `pagination.nextCursor` as opaque and reuse it unchanged.
- Use `get_paper_details`, `get_paper_citations`, `get_paper_references`,
  and `get_paper_authors` to expand from a paper you already found.
- Use `search_authors`, `get_author_info`, and `get_author_papers`
  for author-centric workflows.
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
    )


settings = AppSettings.from_env()
api_key = settings.semantic_scholar_api_key
core_api_key = settings.core_api_key
serpapi_api_key = settings.serpapi_api_key
enable_core = settings.enable_core
enable_semantic_scholar = settings.enable_semantic_scholar
enable_arxiv = settings.enable_arxiv
enable_serpapi = settings.enable_serpapi
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
        "Start with search_papers for quick discovery, inspect brokerMetadata, use "
        "search_papers_bulk when pagination or exhaustive retrieval is needed, and "
        "reuse pagination.nextCursor exactly as returned."
    )


http_app_transport = cast(
    Literal["http", "streamable-http", "sse"],
    settings.transport if settings.transport != "stdio" else "streamable-http",
)
http_app = app.http_app(path=settings.http_path, transport=http_app_transport)


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
