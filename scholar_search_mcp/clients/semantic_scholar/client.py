"""Semantic Scholar API client."""

import logging
import time
from typing import Any, Optional

from ...constants import (
    API_BASE_URL,
    DEFAULT_AUTHOR_FIELDS,
    DEFAULT_PAPER_FIELDS,
    MAX_429_RETRIES,
    RECOMMENDATIONS_BASE_URL,
    SEMANTIC_SCHOLAR_MIN_INTERVAL,
)
from ...models import (
    AuthorListResponse,
    AuthorProfile,
    BatchAuthorResponse,
    BatchPaperResponse,
    BulkSearchResponse,
    Paper,
    PaperAuthorListResponse,
    PaperListResponse,
    RecommendationResponse,
    SemanticSearchResponse,
    SnippetSearchResponse,
    dump_jsonable,
)
from ...transport import asyncio, httpx

logger = logging.getLogger("scholar-search-mcp")


class SemanticScholarClient:
    """Semantic Scholar API client.

    One shared rate limiter (``_rate_lock`` + ``_last_request_time``) enforces the
    documented ``1 request per second`` ceiling across *all* endpoints.  The limiter
    lives on the instance so that a single application-level client instance shares
    the budget, matching the guide's advice to keep one limiter per service client.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.headers: dict[str, str] = {}
        if api_key:
            self.headers["x-api-key"] = api_key
        # Lazily initialized in async context (avoids event-loop binding issues).
        self._rate_lock: Optional[asyncio.Lock] = None
        self._last_request_time: float = 0.0

    def _get_rate_lock(self) -> asyncio.Lock:
        if self._rate_lock is None:
            self._rate_lock = asyncio.Lock()
        return self._rate_lock

    async def _pace(self) -> None:
        """Enforce the 1 request/second ceiling before every outbound request."""
        lock = self._get_rate_lock()
        async with lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < SEMANTIC_SCHOLAR_MIN_INTERVAL:
                await asyncio.sleep(SEMANTIC_SCHOLAR_MIN_INTERVAL - elapsed)
            self._last_request_time = time.monotonic()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
        base_url: Optional[str] = None,
        max_retries: int = 4,
        base_delay: float = 1.0,
    ) -> Any:
        """Send HTTP request with rate pacing and exponential backoff on 429.

        ``_pace()`` is called before *every* attempt (including retries after
        a 429) so that the shared cross-endpoint rate limit is honoured even
        when a previous attempt was rejected.
        """
        resolved_base = base_url if base_url is not None else API_BASE_URL
        url = f"{resolved_base}/{endpoint}"
        total_attempts = max(max_retries, MAX_429_RETRIES) + 1

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(total_attempts):
                await self._pace()
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=json_data,
                )

                if response.status_code == 429:
                    if attempt < MAX_429_RETRIES:
                        delay = base_delay * (2**attempt)
                        retry_after = response.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            delay = max(delay, float(retry_after))
                        logger.warning(
                            "Rate limited (429), retrying in %.1fs (%s/%s)",
                            delay,
                            attempt + 1,
                            MAX_429_RETRIES,
                        )
                        await asyncio.sleep(delay)
                        continue

                    response.raise_for_status()

                response.raise_for_status()
                return response.json()

        raise RuntimeError("Semantic Scholar request retry loop exited unexpectedly")

    async def aclose(self) -> None:
        """No-op; kept for API symmetry with guide examples that call ``aclose``."""

    # ------------------------------------------------------------------
    # Paper search
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_match_response(response: Any) -> Paper:
        """Normalize best-match responses to one paper payload.

        The upstream endpoint normally returns a single paper object, but some
        observed responses have wrapped the match inside ``data[0]`` while also
        including top-level paper keys with null values. Prefer the nested paper
        payload when present so callers always receive one unambiguous
        paper-shaped response.
        """
        if isinstance(response, dict):
            nested_matches = response.get("data")
            if isinstance(nested_matches, list):
                for candidate in nested_matches:
                    if isinstance(candidate, dict):
                        return Paper.model_validate(candidate)
        return Paper.model_validate(response)

    async def search_papers(
        self,
        query: str,
        limit: int = 10,
        fields: Optional[list[str]] = None,
        year: Optional[str] = None,
        venue: Optional[list[str]] = None,
        offset: Optional[int] = None,
        publication_date_or_year: Optional[str] = None,
        fields_of_study: Optional[str] = None,
        publication_types: Optional[str] = None,
        open_access_pdf: Optional[bool] = None,
        min_citation_count: Optional[int] = None,
    ) -> dict[str, Any]:
        """Relevance-ranked paper search (``/paper/search``)."""
        params: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        if offset is not None:
            params["offset"] = offset
        if year:
            params["year"] = year
        if venue:
            params["venue"] = ",".join(venue)
        if publication_date_or_year:
            params["publicationDateOrYear"] = publication_date_or_year
        if fields_of_study:
            params["fieldsOfStudy"] = fields_of_study
        if publication_types:
            params["publicationTypes"] = publication_types
        if open_access_pdf:
            params["openAccessPdf"] = ""
        if min_citation_count is not None:
            params["minCitationCount"] = min_citation_count
        response = await self._request("GET", "paper/search", params=params)
        return dump_jsonable(SemanticSearchResponse.model_validate(response))

    async def search_papers_bulk(
        self,
        query: str,
        fields: Optional[list[str]] = None,
        token: Optional[str] = None,
        sort: Optional[str] = None,
        limit: int = 100,
        year: Optional[str] = None,
        publication_date_or_year: Optional[str] = None,
        fields_of_study: Optional[str] = None,
        publication_types: Optional[str] = None,
        open_access_pdf: Optional[bool] = None,
        min_citation_count: Optional[int] = None,
    ) -> dict[str, Any]:
        """Bulk paper search with token-based pagination (``/paper/search/bulk``).

        Supports up to 1,000 papers per call and advanced boolean query syntax.
        Repeat the call with the returned ``token`` until the response contains no
        token to paginate through up to 10,000,000 results.
        """
        params: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 1000),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        if token:
            params["token"] = token
        if sort:
            params["sort"] = sort
        if year:
            params["year"] = year
        if publication_date_or_year:
            params["publicationDateOrYear"] = publication_date_or_year
        if fields_of_study:
            params["fieldsOfStudy"] = fields_of_study
        if publication_types:
            params["publicationTypes"] = publication_types
        if open_access_pdf:
            params["openAccessPdf"] = ""
        if min_citation_count is not None:
            params["minCitationCount"] = min_citation_count
        response = await self._request("GET", "paper/search/bulk", params=params)
        return dump_jsonable(BulkSearchResponse.model_validate(response))

    async def search_papers_match(
        self,
        query: str,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Best title-match paper search (``/paper/search/match``).

        Returns the single paper whose title most closely matches *query*.
        """
        params: dict[str, Any] = {
            "query": query,
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        response = await self._request("GET", "paper/search/match", params=params)
        return dump_jsonable(self._normalize_match_response(response))

    async def paper_autocomplete(self, query: str) -> dict[str, Any]:
        """Query completion for paper titles (``/paper/autocomplete``).

        Designed for typeahead or interactive search UI.  Returns a list of
        matching title completions; raw API response is returned as-is.
        """
        params: dict[str, Any] = {"query": query}
        return await self._request("GET", "paper/autocomplete", params=params)

    # ------------------------------------------------------------------
    # Paper detail / sub-resources
    # ------------------------------------------------------------------

    async def get_paper_details(
        self,
        paper_id: str,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get paper details (``/paper/{paper_id}``)."""
        params = {"fields": ",".join(fields or DEFAULT_PAPER_FIELDS)}
        response = await self._request("GET", f"paper/{paper_id}", params=params)
        return dump_jsonable(Paper.model_validate(response))

    async def get_paper_citations(
        self,
        paper_id: str,
        limit: int = 100,
        fields: Optional[list[str]] = None,
        offset: Optional[int] = None,
    ) -> dict[str, Any]:
        """Get papers that cite this paper (``/paper/{paper_id}/citations``)."""
        params: dict[str, Any] = {
            "limit": min(limit, 1000),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        if offset is not None:
            params["offset"] = offset
        response = await self._request(
            "GET",
            f"paper/{paper_id}/citations",
            params=params,
        )
        return dump_jsonable(PaperListResponse.model_validate(response))

    async def get_paper_references(
        self,
        paper_id: str,
        limit: int = 100,
        fields: Optional[list[str]] = None,
        offset: Optional[int] = None,
    ) -> dict[str, Any]:
        """Get paper references (``/paper/{paper_id}/references``)."""
        params: dict[str, Any] = {
            "limit": min(limit, 1000),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        if offset is not None:
            params["offset"] = offset
        response = await self._request(
            "GET",
            f"paper/{paper_id}/references",
            params=params,
        )
        return dump_jsonable(PaperListResponse.model_validate(response))

    async def get_paper_authors(
        self,
        paper_id: str,
        limit: int = 100,
        fields: Optional[list[str]] = None,
        offset: Optional[int] = None,
    ) -> dict[str, Any]:
        """Get authors of a paper (``/paper/{paper_id}/authors``)."""
        params: dict[str, Any] = {
            "limit": min(limit, 1000),
            "fields": ",".join(fields or DEFAULT_AUTHOR_FIELDS),
        }
        if offset is not None:
            params["offset"] = offset
        response = await self._request(
            "GET",
            f"paper/{paper_id}/authors",
            params=params,
        )
        return dump_jsonable(PaperAuthorListResponse.model_validate(response))

    # ------------------------------------------------------------------
    # Author endpoints
    # ------------------------------------------------------------------

    async def get_author_info(
        self,
        author_id: str,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get author info (``/author/{author_id}``)."""
        params = {"fields": ",".join(fields or DEFAULT_AUTHOR_FIELDS)}
        response = await self._request("GET", f"author/{author_id}", params=params)
        return dump_jsonable(AuthorProfile.model_validate(response))

    async def get_author_papers(
        self,
        author_id: str,
        limit: int = 100,
        fields: Optional[list[str]] = None,
        offset: Optional[int] = None,
        publication_date_or_year: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get papers by an author (``/author/{author_id}/papers``)."""
        params: dict[str, Any] = {
            "limit": min(limit, 1000),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        if offset is not None:
            params["offset"] = offset
        if publication_date_or_year:
            params["publicationDateOrYear"] = publication_date_or_year
        response = await self._request(
            "GET",
            f"author/{author_id}/papers",
            params=params,
        )
        return dump_jsonable(PaperListResponse.model_validate(response))

    async def search_authors(
        self,
        query: str,
        limit: int = 10,
        fields: Optional[list[str]] = None,
        offset: Optional[int] = None,
    ) -> dict[str, Any]:
        """Search for authors by name (``/author/search``)."""
        params: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 1000),
            "fields": ",".join(fields or DEFAULT_AUTHOR_FIELDS),
        }
        if offset is not None:
            params["offset"] = offset
        response = await self._request("GET", "author/search", params=params)
        return dump_jsonable(AuthorListResponse.model_validate(response))

    async def batch_get_authors(
        self,
        author_ids: list[str],
        fields: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Batch fetch up to 1,000 authors (``POST /author/batch``)."""
        json_data = {"ids": author_ids[:1000]}
        params = {"fields": ",".join(fields or DEFAULT_AUTHOR_FIELDS)}
        response = await self._request(
            "POST",
            "author/batch",
            params=params,
            json_data=json_data,
        )
        return dump_jsonable(BatchAuthorResponse.model_validate(response))

    # ------------------------------------------------------------------
    # Snippet search
    # ------------------------------------------------------------------

    async def search_snippets(
        self,
        query: str,
        limit: int = 10,
        fields: Optional[list[str]] = None,
        year: Optional[str] = None,
        publication_date_or_year: Optional[str] = None,
        fields_of_study: Optional[str] = None,
        min_citation_count: Optional[int] = None,
        venue: Optional[str] = None,
    ) -> dict[str, Any]:
        """Search for matching text snippets (``/snippet/search``)."""
        params: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
        }
        if fields:
            params["fields"] = ",".join(fields)
        if year:
            params["year"] = year
        if publication_date_or_year:
            params["publicationDateOrYear"] = publication_date_or_year
        if fields_of_study:
            params["fieldsOfStudy"] = fields_of_study
        if min_citation_count is not None:
            params["minCitationCount"] = min_citation_count
        if venue:
            params["venue"] = venue
        response = await self._request("GET", "snippet/search", params=params)
        return dump_jsonable(SnippetSearchResponse.model_validate(response))

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    async def get_recommendations(
        self,
        paper_id: str,
        limit: int = 10,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get paper recommendations from one seed paper (GET).

        Uses ``/recommendations/v1/papers/forpaper/{paper_id}``.
        """
        params: dict[str, Any] = {
            "limit": min(limit, 100),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        response = await self._request(
            "GET",
            f"papers/forpaper/{paper_id}",
            params=params,
            base_url=RECOMMENDATIONS_BASE_URL,
        )
        return dump_jsonable(RecommendationResponse.model_validate(response))

    async def get_recommendations_post(
        self,
        positive_paper_ids: list[str],
        negative_paper_ids: Optional[list[str]] = None,
        limit: int = 10,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get recommendations from positive and negative seed sets (POST).

        Uses ``POST /recommendations/v1/papers``.  More flexible than the single-seed
        GET route and typically produces better results for guided retrieval.
        """
        json_data: dict[str, Any] = {
            "positivePaperIds": positive_paper_ids,
        }
        if negative_paper_ids:
            json_data["negativePaperIds"] = negative_paper_ids
        params: dict[str, Any] = {
            "limit": min(limit, 100),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        response = await self._request(
            "POST",
            "papers",
            params=params,
            json_data=json_data,
            base_url=RECOMMENDATIONS_BASE_URL,
        )
        return dump_jsonable(RecommendationResponse.model_validate(response))

    # ------------------------------------------------------------------
    # Batch paper lookup
    # ------------------------------------------------------------------

    async def batch_get_papers(
        self,
        paper_ids: list[str],
        fields: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Batch fetch up to 500 papers (``POST /paper/batch``)."""
        json_data = {"ids": paper_ids[:500]}
        params = {"fields": ",".join(fields or DEFAULT_PAPER_FIELDS)}
        response = await self._request(
            "POST",
            "paper/batch",
            params=params,
            json_data=json_data,
        )
        return dump_jsonable(BatchPaperResponse.model_validate(response))
