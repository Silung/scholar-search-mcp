"""Provider clients for Scholar Search MCP."""

from .arxiv import ArxivClient
from .core import CoreApiClient
from .semantic_scholar import SemanticScholarClient
from .serpapi import SerpApiScholarClient

__all__ = [
    "ArxivClient",
    "CoreApiClient",
    "SemanticScholarClient",
    "SerpApiScholarClient",
]
