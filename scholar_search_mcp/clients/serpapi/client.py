"""SerpApi Google Scholar HTTP client."""

import logging
from typing import Any, Optional

from ...transport import httpx
from .errors import (
    SerpApiError,
    SerpApiKeyMissingError,
    SerpApiQuotaError,
    SerpApiUpstreamError,
)
from .normalize import _parse_year_range, normalize_organic_result

SERPAPI_BASE_URL = "https://serpapi.com/search"

logger = logging.getLogger("scholar-search-mcp")


class SerpApiScholarClient:
    """SerpApi Google Scholar client (https://serpapi.com/google-scholar-api).

    All requests are cache-friendly by default: ``no_cache`` is never set to
    ``true`` so SerpApi serves cached results for identical queries within the
    1-hour cache window.  This avoids burning quota on repeated identical
    requests.

    This is a **paid** upstream API.  Enable it explicitly by setting
    ``SCHOLAR_SEARCH_ENABLE_SERPAPI=true`` and providing ``SERPAPI_API_KEY``.
    """

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def _check_key(self) -> None:
        """Raise ``SerpApiKeyMissingError`` if no API key is configured."""
        if not self.api_key:
            raise SerpApiKeyMissingError(
                "SERPAPI_API_KEY is not configured. "
                "Set the SERPAPI_API_KEY environment variable to use "
                "SerpApi Google Scholar. SerpApi is a paid service — "
                "visit https://serpapi.com to obtain a key. "
                "To disable this provider set SCHOLAR_SEARCH_ENABLE_SERPAPI=false."
            )

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Perform an authenticated GET to the SerpApi endpoint.

        Injects ``api_key`` and translates HTTP/upstream errors into typed
        ``SerpApiError`` subclasses so callers can handle them uniformly.
        """
        self._check_key()
        # Build a clean copy so we don't mutate the caller's dict.
        request_params = dict(params)
        request_params["api_key"] = self.api_key

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(SERPAPI_BASE_URL, params=request_params)
        except Exception as exc:
            logger.warning("SerpApi request failed: %s", exc)
            raise SerpApiUpstreamError(
                f"SerpApi request failed: {exc}. "
                "This may be a transient network error — try again later."
            ) from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "a while")
            raise SerpApiQuotaError(
                f"SerpApi quota or rate limit reached (HTTP 429). "
                f"Retry after {retry_after}. "
                "Consider reducing request frequency or upgrading your SerpApi plan."
            )
        if response.status_code >= 500:
            raise SerpApiUpstreamError(
                f"SerpApi returned HTTP {response.status_code}. "
                "This is a transient upstream error — try again later."
            )
        try:
            response.raise_for_status()
        except Exception as exc:
            raise SerpApiError(
                f"SerpApi returned HTTP {response.status_code}. "
                "Check your API key and request parameters."
            ) from exc

        data: dict[str, Any] = response.json()

        # Translate SerpApi application-level errors.
        error_msg = data.get("error")
        if error_msg:
            msg = str(error_msg).lower()
            if "api_key" in msg or "invalid" in msg or "unauthorized" in msg:
                raise SerpApiKeyMissingError(
                    f"SerpApi authentication error: {error_msg}. "
                    "Check your SERPAPI_API_KEY value."
                )
            if "quota" in msg or "limit" in msg or "credits" in msg:
                raise SerpApiQuotaError(
                    f"SerpApi quota error: {error_msg}. "
                    "Consider upgrading your SerpApi plan."
                )
            raise SerpApiError(
                f"SerpApi returned an error: {error_msg}. "
                "Check your request parameters and try again."
            )

        return data

    async def search(
        self,
        query: str,
        limit: int = 10,
        year: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search Google Scholar via SerpApi.

        Returns a list of normalized paper dicts (up to *limit*, max 20 per
        call since SerpApi Scholar caps organic results at 20 per page).

        *year* accepts the same format used by ``search_papers``:
        ``"2023"`` or ``"2020-2023"``.  It is translated to ``as_ylo`` /
        ``as_yhi`` SerpApi parameters.
        """
        num = min(limit, 20)  # SerpApi Scholar max organic results per page
        params: dict[str, Any] = {
            "engine": "google_scholar",
            # Normalize whitespace for consistent cache hits.
            "q": " ".join(query.strip().split()),
            "num": num,
            "hl": "en",
        }
        if year:
            year_low, year_high = _parse_year_range(year)
            if year_low is not None:
                params["as_ylo"] = year_low
            if year_high is not None:
                params["as_yhi"] = year_high

        data = await self._get(params)
        organic_results: list[dict[str, Any]] = data.get("organic_results") or []

        papers: list[dict[str, Any]] = []
        for result in organic_results[:limit]:
            normalized = normalize_organic_result(result)
            if normalized is not None:
                papers.append(normalized)
        return papers

    async def get_citation_formats(
        self,
        result_id: str,
    ) -> dict[str, Any]:
        """Return citation export formats for a Google Scholar paper.

        Uses the ``google_scholar_cite`` SerpApi engine.  *result_id* is the
        Scholar ``result_id`` from a previous ``search_papers`` call — it is
        available as ``paper.sourceId`` on any ``serpapi_google_scholar``
        result.

        Returns the raw SerpApi response dict containing ``citations`` (text
        formats) and ``links`` (export download links).  The caller is
        responsible for reshaping this into the normalized tool response.

        This is a **paid** SerpApi request (results cached for 1 hour).
        """
        if not result_id or not result_id.strip():
            raise ValueError(
                "result_id must not be empty. "
                "Provide the Scholar result_id from a search_papers result — "
                "it is available as sourceId on serpapi_google_scholar papers."
            )
        params: dict[str, Any] = {
            "engine": "google_scholar_cite",
            "q": result_id.strip(),
        }
        return await self._get(params)
