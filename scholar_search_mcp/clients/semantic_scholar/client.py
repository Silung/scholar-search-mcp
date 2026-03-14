"""Semantic Scholar API client."""

import logging
from typing import Any, Optional

from ...constants import (
    API_BASE_URL,
    DEFAULT_AUTHOR_FIELDS,
    DEFAULT_PAPER_FIELDS,
    MAX_429_RETRIES,
)
from ...models import (
    AuthorProfile,
    BatchPaperResponse,
    Paper,
    PaperListResponse,
    RecommendationResponse,
    SemanticSearchResponse,
    dump_jsonable,
)
from ...transport import asyncio, httpx

logger = logging.getLogger("scholar-search-mcp")


class SemanticScholarClient:
    """Semantic Scholar API client."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.headers: dict[str, str] = {}
        if api_key:
            self.headers["x-api-key"] = api_key

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
        max_retries: int = 4,
        base_delay: float = 1.0,
    ) -> Any:
        """Send HTTP request with exponential backoff on 429."""
        url = f"{API_BASE_URL}/{endpoint}"
        total_attempts = max(max_retries, MAX_429_RETRIES) + 1

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(total_attempts):
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=json_data,
                )

                if response.status_code == 429:
                    if attempt < MAX_429_RETRIES:
                        delay = base_delay * (2 ** attempt)
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

    async def search_papers(
        self,
        query: str,
        limit: int = 10,
        fields: Optional[list[str]] = None,
        year: Optional[str] = None,
        venue: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Search papers."""
        params = {
            "query": query,
            "limit": min(limit, 100),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        if year:
            params["year"] = year
        if venue:
            params["venue"] = ",".join(venue)
        response = await self._request("GET", "paper/search", params=params)
        return dump_jsonable(SemanticSearchResponse.model_validate(response))

    async def get_paper_details(
        self,
        paper_id: str,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get paper details."""
        params = {"fields": ",".join(fields or DEFAULT_PAPER_FIELDS)}
        response = await self._request("GET", f"paper/{paper_id}", params=params)
        return dump_jsonable(Paper.model_validate(response))

    async def get_paper_citations(
        self,
        paper_id: str,
        limit: int = 100,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get papers that cite this paper."""
        params = {
            "limit": min(limit, 1000),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
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
    ) -> dict[str, Any]:
        """Get paper references."""
        params = {
            "limit": min(limit, 1000),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        response = await self._request(
            "GET",
            f"paper/{paper_id}/references",
            params=params,
        )
        return dump_jsonable(PaperListResponse.model_validate(response))

    async def get_author_info(
        self,
        author_id: str,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get author info."""
        params = {"fields": ",".join(fields or DEFAULT_AUTHOR_FIELDS)}
        response = await self._request("GET", f"author/{author_id}", params=params)
        return dump_jsonable(AuthorProfile.model_validate(response))

    async def get_author_papers(
        self,
        author_id: str,
        limit: int = 100,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get author papers."""
        params = {
            "limit": min(limit, 1000),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        response = await self._request(
            "GET",
            f"author/{author_id}/papers",
            params=params,
        )
        return dump_jsonable(PaperListResponse.model_validate(response))

    async def get_recommendations(
        self,
        paper_id: str,
        limit: int = 10,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get paper recommendations."""
        params = {
            "limit": min(limit, 100),
            "fields": ",".join(fields or DEFAULT_PAPER_FIELDS),
        }
        response = await self._request(
            "GET",
            f"recommendations/v1/papers/forpaper/{paper_id}",
            params=params,
        )
        return dump_jsonable(RecommendationResponse.model_validate(response))

    async def batch_get_papers(
        self,
        paper_ids: list[str],
        fields: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Batch get papers (up to 500)."""
        json_data = {"ids": paper_ids[:500]}
        params = {"fields": ",".join(fields or DEFAULT_PAPER_FIELDS)}
        response = await self._request(
            "POST",
            "paper/batch",
            params=params,
            json_data=json_data,
        )
        return dump_jsonable(BatchPaperResponse.model_validate(response))
