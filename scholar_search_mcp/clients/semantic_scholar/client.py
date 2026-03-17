"""Semantic Scholar API client."""

import logging
import re
import time
from difflib import SequenceMatcher
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
_AUTHOR_QUERY_QUOTES_PATTERN = re.compile(r'["“”‘’`]+')
_AUTHOR_QUERY_PUNCTUATION_PATTERN = re.compile(r"[,;()]+")
_AUTHOR_QUERY_INITIAL_PERIOD_PATTERN = re.compile(r"(?<=\w)\.(?=\s|$)")
_AUTHOR_QUERY_WHITESPACE_PATTERN = re.compile(r"\s+")
_TITLE_LOOKUP_QUOTES_PATTERN = re.compile(r'["“”‘’`]+')
_TITLE_LOOKUP_PUNCTUATION_PATTERN = re.compile(r"[-–—:;,/?!()]+")
_TITLE_LOOKUP_KEY_PATTERN = re.compile(r"[^0-9a-z]+")
# Keep fuzzy-title recovery conservative: exact normalized matches win, and
# otherwise require very high similarity to avoid promoting unrelated papers.
_TITLE_MATCH_SIMILARITY_THRESHOLD = 0.92
# Fallback only needs a small relevance-ranked window because we re-score titles
# locally and want to keep degraded exact-match recovery cheap.
_TITLE_MATCH_FALLBACK_LIMIT = 10


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

    @staticmethod
    def _normalize_nested_paper_list_response(
        response: Any,
        nested_key: str,
    ) -> PaperListResponse:
        """Normalize list endpoints that wrap each paper under a nested key."""
        if isinstance(response, dict):
            normalized = dict(response)
            raw_items = normalized.get("data")
            if isinstance(raw_items, list):
                normalized["data"] = [
                    item.get(nested_key, item) if isinstance(item, dict) else item
                    for item in raw_items
                ]
            response = normalized
        return PaperListResponse.model_validate(response)

    @staticmethod
    def _status_code_from_error(exc: Exception) -> int | None:
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None)

    @staticmethod
    def _normalize_author_search_query(query: str) -> str:
        normalized = _AUTHOR_QUERY_QUOTES_PATTERN.sub(" ", query.strip())
        normalized = _AUTHOR_QUERY_PUNCTUATION_PATTERN.sub(" ", normalized)
        normalized = _AUTHOR_QUERY_INITIAL_PERIOD_PATTERN.sub("", normalized)
        normalized = _AUTHOR_QUERY_WHITESPACE_PATTERN.sub(" ", normalized).strip()
        return normalized or query.strip()

    @staticmethod
    def _paper_id_portability_hint() -> str:
        return (
            "If this paper came from brokered CORE, arXiv, or SerpApi results, retry "
            "with paper.recommendedExpansionId when it is present. If "
            "paper.expansionIdStatus is not_portable, resolve the paper through "
            "DOI or a Semantic Scholar-native lookup instead of reusing "
            "provider-specific paperId, sourceId, or canonicalId values."
        )

    @staticmethod
    def _enrich_bulk_paper(paper: Paper) -> Paper:
        """Enrich a bulk search result paper with SS expansion ID portability fields.

        Mirrors ``_enrich_ss_paper`` in ``search.py`` so that ``search_papers_bulk``
        results expose the same ``recommendedExpansionId`` / ``expansionIdStatus``
        signals as brokered ``search_papers_semantic_scholar`` results.
        """
        external_ids: dict[str, Any] = (
            (paper.model_extra or {}).get("externalIds") or {}
        )
        doi: str | None = external_ids.get("DOI") or None
        arxiv_id: str | None = external_ids.get("ArXiv") or None
        paper_id: str | None = paper.paper_id
        source_id = paper_id
        canonical_id: str | None = doi or paper_id or arxiv_id or source_id
        return paper.model_copy(
            update={
                "source": paper.source or "semantic_scholar",
                "source_id": source_id,
                "canonical_id": canonical_id,
                "recommended_expansion_id": canonical_id,
                "expansion_id_status": "portable",
            }
        )

    @staticmethod
    def _normalize_title_lookup_query(query: str) -> str:
        normalized = _TITLE_LOOKUP_QUOTES_PATTERN.sub(" ", query.strip())
        normalized = _TITLE_LOOKUP_PUNCTUATION_PATTERN.sub(" ", normalized)
        normalized = _AUTHOR_QUERY_WHITESPACE_PATTERN.sub(" ", normalized).strip()
        return normalized or query.strip()

    @classmethod
    def _title_lookup_queries(cls, query: str) -> list[str]:
        queries: list[str] = []
        for candidate in (query.strip(), cls._normalize_title_lookup_query(query)):
            if candidate and candidate not in queries:
                queries.append(candidate)
        return queries

    @staticmethod
    def _normalize_title_match_key(value: str) -> str:
        normalized = _TITLE_LOOKUP_KEY_PATTERN.sub(" ", value.lower())
        normalized = _AUTHOR_QUERY_WHITESPACE_PATTERN.sub(" ", normalized).strip()
        return normalized

    @classmethod
    def _pick_title_match_candidate(
        cls,
        query: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        target_key = cls._normalize_title_match_key(query)
        if not target_key:
            return None

        best_candidate: dict[str, Any] | None = None
        best_score: tuple[int, float] = (-1, -1.0)
        for candidate in candidates:
            title = candidate.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            candidate_key = cls._normalize_title_match_key(title)
            if not candidate_key:
                continue
            exact = candidate_key == target_key
            containment = target_key in candidate_key or candidate_key in target_key
            ratio = SequenceMatcher(None, target_key, candidate_key).ratio()
            score = (2 if exact else 1 if containment else 0, ratio)
            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate is None:
            return None

        exactish, ratio = best_score
        if exactish > 0 or ratio >= _TITLE_MATCH_SIMILARITY_THRESHOLD:
            return best_candidate
        return None

    async def _search_papers_match_fallback(
        self,
        query: str,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        candidate_queries = self._title_lookup_queries(query)
        for candidate_query in candidate_queries:
            try:
                fallback_response = await self.search_papers(
                    candidate_query,
                    limit=_TITLE_MATCH_FALLBACK_LIMIT,
                    fields=fields,
                )
            except httpx.HTTPStatusError:
                continue
            matched = self._pick_title_match_candidate(
                query,
                fallback_response.get("data", []),
            )
            if matched is None:
                continue
            payload = dump_jsonable(Paper.model_validate(matched))
            payload["matchFound"] = True
            payload["matchStrategy"] = "fuzzy_search"
            if candidate_query != query.strip():
                payload["normalizedQuery"] = candidate_query
            return payload

        return {
            "paperId": None,
            "title": None,
            "query": query,
            "matchFound": False,
            "matchStrategy": "none",
            "normalizedQueriesTried": candidate_queries,
            "message": (
                "No Semantic Scholar title match was found. This query may refer to "
                "a dissertation, software release, report, or other output outside "
                "the indexed paper surface. Try search_papers, search_authors, or "
                "external verification."
            ),
        }

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

        Supports advanced boolean query syntax and provider-sized bulk pages.
        The upstream endpoint may ignore small ``limit`` values and still return
        a full bulk batch, so the client truncates the returned ``data`` list to
        the requested limit after normalization while preserving the returned
        ``token`` for continuation. Repeat the call with the returned ``token``
        until the response contains no token to paginate through up to
        10,000,000 results.
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
        parsed = BulkSearchResponse.model_validate(response)
        if len(parsed.data) > limit:
            parsed.data = parsed.data[:limit]
        parsed.data = [self._enrich_bulk_paper(paper) for paper in parsed.data]
        return dump_jsonable(parsed)

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
        try:
            response = await self._request("GET", "paper/search/match", params=params)
        except httpx.HTTPStatusError as exc:
            status_code = self._status_code_from_error(exc)
            if status_code in {400, 404}:
                return await self._search_papers_match_fallback(query, fields=fields)
            raise
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
        return dump_jsonable(
            self._normalize_nested_paper_list_response(response, "citingPaper")
        )

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
        return dump_jsonable(
            self._normalize_nested_paper_list_response(response, "citedPaper")
        )

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
        try:
            response = await self._request(
                "GET",
                f"paper/{paper_id}/authors",
                params=params,
            )
        except httpx.HTTPStatusError as exc:
            status_code = self._status_code_from_error(exc)
            if status_code == 404:
                raise ValueError(
                    f"Semantic Scholar could not find paper {paper_id!r} for "
                    "get_paper_authors. This tool only accepts Semantic "
                    "Scholar-compatible paper identifiers. "
                    f"{self._paper_id_portability_hint()}"
                ) from exc
            if status_code == 400:
                raise ValueError(
                    f"Semantic Scholar rejected paper identifier {paper_id!r} for "
                    "get_paper_authors. Use a Semantic Scholar-compatible paper "
                    f"identifier. {self._paper_id_portability_hint()}"
                ) from exc
            raise
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
        try:
            response = await self._request("GET", f"author/{author_id}", params=params)
        except httpx.HTTPStatusError as exc:
            status_code = self._status_code_from_error(exc)
            if status_code == 400:
                raise ValueError(
                    f"Semantic Scholar rejected get_author_info for author "
                    f"{author_id!r}. Requested author fields: {params['fields']}. "
                    "Use only supported author fields and pass a Semantic Scholar "
                    "authorId returned by search_authors or get_paper_authors."
                ) from exc
            if status_code == 404:
                raise ValueError(
                    f"Semantic Scholar could not find author {author_id!r}. "
                    "Use a Semantic Scholar authorId returned by search_authors "
                    "or get_paper_authors."
                ) from exc
            raise
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
        try:
            response = await self._request(
                "GET",
                f"author/{author_id}/papers",
                params=params,
            )
        except httpx.HTTPStatusError as exc:
            status_code = self._status_code_from_error(exc)
            if status_code == 400:
                raise ValueError(
                    f"Semantic Scholar rejected get_author_papers for author "
                    f"{author_id!r}. Use a Semantic Scholar authorId returned by "
                    "search_authors or get_paper_authors."
                ) from exc
            if status_code == 404:
                raise ValueError(
                    f"Semantic Scholar could not find author {author_id!r} for "
                    "get_author_papers. Use a Semantic Scholar authorId returned by "
                    "search_authors or get_paper_authors."
                ) from exc
            raise
        return dump_jsonable(PaperListResponse.model_validate(response))

    async def search_authors(
        self,
        query: str,
        limit: int = 10,
        fields: Optional[list[str]] = None,
        offset: Optional[int] = None,
    ) -> dict[str, Any]:
        """Search for authors by name (``/author/search``)."""
        normalized_query = self._normalize_author_search_query(query)
        params: dict[str, Any] = {
            "query": normalized_query,
            "limit": min(limit, 1000),
            "fields": ",".join(fields or DEFAULT_AUTHOR_FIELDS),
        }
        if offset is not None:
            params["offset"] = offset
        try:
            response = await self._request("GET", "author/search", params=params)
        except httpx.HTTPStatusError as exc:
            if self._status_code_from_error(exc) == 400:
                raise ValueError(
                    f"Semantic Scholar rejected author search query {query!r}. "
                    "search_authors only supports plain-text name queries. "
                    f"The MCP server normalized the query to {normalized_query!r}; "
                    "if the request still fails, retry without quotes, boolean "
                    "operators, or other special syntax. For common names, add "
                    "affiliation, coauthor, venue, or topic clues and then confirm "
                    "the best candidate with get_author_info/get_author_papers."
                ) from exc
            raise
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
        try:
            response = await self._request("GET", "snippet/search", params=params)
        except httpx.HTTPStatusError as exc:
            status_code = self._status_code_from_error(exc)
            if status_code in {400, 404, 500, 502, 503, 504}:
                payload = dump_jsonable(SnippetSearchResponse(data=[]))
                payload["query"] = query
                payload["degraded"] = True
                payload["message"] = (
                    "Semantic Scholar snippet search could not serve this query, so "
                    "the server returned an empty result instead of surfacing the raw "
                    "provider error. Retry with a shorter plain-text phrase or fall "
                    "back to search_papers_match/search_papers."
                )
                payload["providerStatusCode"] = status_code
                return payload
            raise
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
