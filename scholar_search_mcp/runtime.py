"""Runtime boot helpers for the FastMCP server."""

from typing import Any

from .settings import AppSettings

LOCAL_HTTP_HOSTS = {"127.0.0.1", "localhost", "::1"}


def run_server(*, app: Any, logger: Any, settings: AppSettings) -> None:
    """Run the MCP server over the configured FastMCP transport."""
    logger.info("Starting Scholar Search MCP Server...")
    logger.info("FastMCP transport: %s", settings.transport)
    logger.info(
        "Search channels: CORE=%s, Semantic Scholar=%s, SerpApi=%s, arXiv=%s",
        settings.enable_core,
        settings.enable_semantic_scholar,
        settings.enable_serpapi,
        settings.enable_arxiv,
    )
    if settings.semantic_scholar_api_key:
        logger.info("Semantic Scholar API key detected")
    else:
        logger.warning("No Semantic Scholar API key; using public rate limits")
    if settings.core_api_key:
        logger.info("CORE API key set (search tries CORE first with higher limits)")
    else:
        logger.info(
            "No CORE API key; search still tries CORE first "
            "(subject to rate limits), then S2/arXiv"
        )
    if settings.enable_serpapi:
        if settings.serpapi_api_key:
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

    if settings.transport == "stdio":
        app.run(transport="stdio")
        return

    logger.info(
        "HTTP transports are currently intended for local/dev/integration use. "
        "Before exposing the server remotely, add Origin validation, "
        "authentication, and TLS via scholar_search_mcp.server.build_http_app(...) "
        "or an enclosing ASGI app."
    )
    if settings.http_host not in LOCAL_HTTP_HOSTS:
        logger.warning(
            "Binding HTTP transport to %s. MCP HTTP guidance expects Origin "
            "validation and recommends authentication before remote exposure.",
            settings.http_host,
        )

    logger.info(
        "Serving MCP over %s at http://%s:%s%s",
        settings.transport,
        settings.http_host,
        settings.http_port,
        settings.http_path,
    )
    app.run(
        transport=settings.transport,
        host=settings.http_host,
        port=settings.http_port,
        path=settings.http_path,
    )
