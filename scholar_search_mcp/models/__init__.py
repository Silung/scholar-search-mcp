"""Shared Pydantic models and helpers."""

from .common import (
    ApiModel,
    ArxivSearchResponse,
    Author,
    AuthorProfile,
    BatchPaperResponse,
    CoreSearchResponse,
    Paper,
    PaperListResponse,
    RecommendationResponse,
    SearchResponse,
    SemanticSearchResponse,
    dump_jsonable,
)
from .tools import TOOL_INPUT_MODELS

__all__ = [
    "ApiModel",
    "ArxivSearchResponse",
    "Author",
    "AuthorProfile",
    "BatchPaperResponse",
    "CoreSearchResponse",
    "Paper",
    "PaperListResponse",
    "RecommendationResponse",
    "SearchResponse",
    "SemanticSearchResponse",
    "TOOL_INPUT_MODELS",
    "dump_jsonable",
]