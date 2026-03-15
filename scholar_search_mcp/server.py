"""Compatibility facade for the Scholar Search MCP public server surface."""

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

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
from .models import dump_jsonable
from .parsing import _arxiv_id_from_url, _text
from .runtime import run_server
from .search import _core_response_to_merged, _merge_search_results
from .settings import AppSettings, _env_bool
from .tools import get_tool_definitions
from .transport import asyncio, httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scholar-search-mcp")

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


app = Server("scholar-search")
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


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return get_tool_definitions()


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    result = await dispatch_tool(
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

    return [
        TextContent(
            type="text",
            text=json.dumps(dump_jsonable(result), ensure_ascii=False, indent=2),
        )
    ]


def main() -> None:
    """Run the MCP server."""
    run_server(
        app=app,
        logger=logger,
        enable_core=enable_core,
        enable_semantic_scholar=enable_semantic_scholar,
        enable_arxiv=enable_arxiv,
        enable_serpapi=enable_serpapi,
        api_key=api_key,
        core_api_key=core_api_key,
        serpapi_api_key=serpapi_api_key,
    )


if __name__ == "__main__":
    main()
