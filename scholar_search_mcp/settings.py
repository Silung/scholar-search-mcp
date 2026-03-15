"""Environment-backed settings helpers."""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict


def _env_bool(key: str, default: bool = True) -> bool:
    """Parse env as bool: 1/true/yes => True; 0/false/no => False."""
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes")


def _parse_env_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    value = env.get(key)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes")


class AppSettings(BaseModel):
    """Typed application settings loaded from environment variables."""

    model_config = ConfigDict(frozen=True)

    semantic_scholar_api_key: str | None = None
    core_api_key: str | None = None
    serpapi_api_key: str | None = None
    enable_core: bool = True
    enable_semantic_scholar: bool = True
    enable_arxiv: bool = True
    enable_serpapi: bool = False
    transport: Literal["stdio", "http", "streamable-http", "sse"] = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    http_path: str = "/mcp"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AppSettings":
        env = environ if environ is not None else os.environ
        return cls(
            semantic_scholar_api_key=env.get("SEMANTIC_SCHOLAR_API_KEY"),
            core_api_key=env.get("CORE_API_KEY"),
            serpapi_api_key=env.get("SERPAPI_API_KEY"),
            enable_core=_parse_env_bool(env, "SCHOLAR_SEARCH_ENABLE_CORE", True),
            enable_semantic_scholar=_parse_env_bool(
                env,
                "SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR",
                True,
            ),
            enable_arxiv=_parse_env_bool(env, "SCHOLAR_SEARCH_ENABLE_ARXIV", True),
            enable_serpapi=_parse_env_bool(
                env,
                "SCHOLAR_SEARCH_ENABLE_SERPAPI",
                False,
            ),
            transport=cast_transport(env.get("SCHOLAR_SEARCH_TRANSPORT")),
            http_host=env.get("SCHOLAR_SEARCH_HTTP_HOST", "127.0.0.1"),
            http_port=int(env.get("SCHOLAR_SEARCH_HTTP_PORT", "8000")),
            http_path=env.get("SCHOLAR_SEARCH_HTTP_PATH", "/mcp"),
        )


def cast_transport(value: str | None) -> Literal["stdio", "http", "streamable-http", "sse"]:
    """Normalize the configured FastMCP transport."""
    if value is None or value == "":
        return "stdio"
    normalized = value.strip().lower()
    if normalized in {"stdio", "http", "streamable-http", "sse"}:
        return normalized
    raise ValueError(
        "SCHOLAR_SEARCH_TRANSPORT must be one of: "
        "stdio, http, streamable-http, sse"
    )
