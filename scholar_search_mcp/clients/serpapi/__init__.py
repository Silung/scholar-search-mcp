"""SerpApi Google Scholar client subpackage."""

from .client import SerpApiScholarClient
from .errors import (
    SerpApiError,
    SerpApiKeyMissingError,
    SerpApiQuotaError,
    SerpApiUpstreamError,
)

__all__ = [
    "SerpApiScholarClient",
    "SerpApiError",
    "SerpApiKeyMissingError",
    "SerpApiQuotaError",
    "SerpApiUpstreamError",
]
