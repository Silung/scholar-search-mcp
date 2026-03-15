"""SerpApi error types."""


class SerpApiError(Exception):
    """Base class for SerpApi errors."""


class SerpApiKeyMissingError(SerpApiError):
    """Raised when the SerpApi API key is not configured."""


class SerpApiQuotaError(SerpApiError):
    """Raised when SerpApi returns a quota or rate-limit error (HTTP 429)."""


class SerpApiUpstreamError(SerpApiError):
    """Raised for transient upstream failures (HTTP 5xx or network errors)."""
