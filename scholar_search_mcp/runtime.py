"""Runtime boot helpers for the MCP server."""

from typing import Any


def run_server(
    *,
    app: Any,
    logger: Any,
    enable_core: bool,
    enable_semantic_scholar: bool,
    enable_arxiv: bool,
    enable_serpapi: bool = False,
    api_key: str | None,
    core_api_key: str | None,
    serpapi_api_key: str | None = None,
) -> None:
    """Run the MCP server over stdio."""
    import anyio
    from mcp.server.stdio import stdio_server

    logger.info("Starting Scholar Search MCP Server...")
    logger.info(
        "Search channels: CORE=%s, Semantic Scholar=%s, SerpApi=%s, arXiv=%s",
        enable_core,
        enable_semantic_scholar,
        enable_serpapi,
        enable_arxiv,
    )
    if api_key:
        logger.info("Semantic Scholar API key detected")
    else:
        logger.warning("No Semantic Scholar API key; using public rate limits")
    if core_api_key:
        logger.info("CORE API key set (search tries CORE first with higher limits)")
    else:
        logger.info(
            "No CORE API key; search still tries CORE first "
            "(subject to rate limits), then S2/arXiv"
        )
    if enable_serpapi:
        if serpapi_api_key:
            logger.info("SerpApi Google Scholar enabled with API key")
        else:
            logger.warning(
                "SerpApi Google Scholar is enabled but SERPAPI_API_KEY is not set; "
                "calls to SerpApi-backed tools will fail with a helpful error"
            )
    else:
        logger.info(
            "SerpApi Google Scholar is disabled (set "
            "SCHOLAR_SEARCH_ENABLE_SERPAPI=true and SERPAPI_API_KEY to enable)"
        )

    async def arun() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )

    anyio.run(arun)
