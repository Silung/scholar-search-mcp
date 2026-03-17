"""OpenAlex API client."""

import logging
import time
from typing import Any, Optional

from ...models import Author, AuthorProfile, Paper, dump_jsonable
from ...transport import asyncio, httpx

logger = logging.getLogger("scholar-search-mcp")

OPENALEX_API_BASE = "https://api.openalex.org"
OPENALEX_LIST_SELECT = (
    "id,doi,display_name,publication_year,publication_date,"
    "authorships,cited_by_count,referenced_works_count,primary_location,"
    "best_oa_location,type"
)
OPENALEX_DETAIL_SELECT = (
    "id,doi,display_name,publication_year,publication_date,"
    "authorships,cited_by_count,referenced_works,referenced_works_count,"
    "cited_by_api_url,primary_location,best_oa_location,type,"
    "abstract_inverted_index,related_works"
)
OPENALEX_AUTHOR_SELECT = (
    "id,display_name,works_count,cited_by_count,summary_stats,"
    "last_known_institutions,orcid,works_api_url"
)


class OpenAlexClient:
    """OpenAlex client for explicit provider-specific MCP tools."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        mailto: Optional[str] = None,
        timeout: float = 30.0,
        min_interval: float = 0.05,
        max_retries: int = 2,
        base_delay: float = 0.5,
    ):
        self.api_key = api_key
        self.mailto = mailto.strip() if mailto else None
        self.timeout = timeout
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._rate_lock: Optional[asyncio.Lock] = None
        self._last_request_time: float = 0.0

    def _get_rate_lock(self) -> asyncio.Lock:
        if self._rate_lock is None:
            self._rate_lock = asyncio.Lock()
        return self._rate_lock

    async def _pace(self) -> None:
        lock = self._get_rate_lock()
        async with lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_request_time = time.monotonic()

    def _default_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.mailto:
            params["mailto"] = self.mailto
        return params

    async def _request(
        self,
        endpoint: str,
        *,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = (
            endpoint
            if endpoint.startswith("http")
            else f"{OPENALEX_API_BASE}{endpoint}"
        )
        request_params = {**self._default_params(), **(params or {})}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries + 1):
                await self._pace()
                response = await client.get(
                    url,
                    params=request_params,
                    follow_redirects=True,
                )
                if (
                    response.status_code in {429, 500, 502, 503, 504}
                    and attempt < self.max_retries
                ):
                    delay = self.base_delay * (2**attempt)
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = max(delay, float(retry_after))
                    logger.warning(
                        "OpenAlex request to %s returned %s, retrying in %.1fs (%s/%s)",
                        url,
                        response.status_code,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                return response.json()
        raise RuntimeError("OpenAlex request retry loop exited unexpectedly")

    @staticmethod
    def _normalize_doi(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        if lowered.startswith("doi:"):
            normalized = normalized[4:].strip()
        elif lowered.startswith("https://doi.org/"):
            normalized = normalized[16:]
        elif lowered.startswith("http://doi.org/"):
            normalized = normalized[15:]
        elif not normalized.startswith("10."):
            return None
        normalized = normalized.strip().lstrip("/")
        return normalized or None

    @staticmethod
    def _extract_openalex_id(value: Any, prefix: str) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        for candidate_prefix in (
            f"https://openalex.org/{prefix.lower()}",
            f"http://openalex.org/{prefix.lower()}",
            f"https://api.openalex.org/works/{prefix.lower()}",
            f"https://api.openalex.org/authors/{prefix.lower()}",
        ):
            if lowered.startswith(candidate_prefix):
                normalized = normalized.rstrip("/").rsplit("/", 1)[-1]
                break
        if normalized.upper().startswith(prefix) and normalized[1:].isdigit():
            return normalized.upper()
        return None

    @classmethod
    def _normalize_work_lookup(cls, value: str) -> tuple[str | None, str | None]:
        return cls._extract_openalex_id(value, "W"), cls._normalize_doi(value)

    @classmethod
    def _normalize_author_id(cls, value: str) -> str:
        author_id = cls._extract_openalex_id(value, "A")
        if author_id is None:
            raise ValueError(
                "OpenAlex author_id must be an OpenAlex A-id or OpenAlex author URL."
            )
        return author_id

    @staticmethod
    def _reconstruct_abstract(index: Any) -> str | None:
        if not isinstance(index, dict) or not index:
            return None
        positions: dict[int, str] = {}
        for word, word_positions in index.items():
            if not isinstance(word, str) or not isinstance(word_positions, list):
                return None
            for position in word_positions:
                if not isinstance(position, int):
                    return None
                positions[position] = word
        if not positions:
            return None
        return " ".join(positions[pos] for pos in sorted(positions))

    @staticmethod
    def _authors_from_authorships(authorships: Any) -> tuple[list[Author], bool]:
        authors: list[Author] = []
        if not isinstance(authorships, list):
            return authors, False
        for authorship in authorships:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author") or {}
            if isinstance(author, dict):
                name = author.get("display_name")
                if isinstance(name, str) and name.strip():
                    authors.append(Author(name=name.strip()))
        return authors, len(authorships) >= 100

    @staticmethod
    def _venue_from_work(work: dict[str, Any]) -> str | None:
        primary_location = work.get("primary_location")
        if not isinstance(primary_location, dict):
            return None
        source = primary_location.get("source")
        if not isinstance(source, dict):
            return None
        display_name = source.get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()
        return None

    @staticmethod
    def _pdf_url_from_work(work: dict[str, Any]) -> str | None:
        for location_key in ("best_oa_location", "primary_location"):
            location = work.get(location_key)
            if not isinstance(location, dict):
                continue
            pdf_url = location.get("pdf_url")
            if isinstance(pdf_url, str) and pdf_url.strip():
                return pdf_url.strip()
        return None

    @staticmethod
    def _combine_filters(*filters: str | None) -> str | None:
        values = [value for value in filters if value]
        return ",".join(values) if values else None

    @staticmethod
    def _year_filters(year: str | None) -> tuple[str | None, str | None]:
        if year is None:
            return None, None
        normalized = year.strip()
        if not normalized:
            return None, None
        if "-" not in normalized:
            single_year = normalized[:4]
            if single_year.isdigit():
                return f"publication_year:{single_year}", None
            return None, None

        start_raw, end_raw = normalized.split("-", maxsplit=1)
        start_year = start_raw.strip()[:4]
        end_year = end_raw.strip()[:4]
        return (
            f"from_publication_date:{start_year}-01-01"
            if start_year.isdigit()
            else None,
            f"to_publication_date:{end_year}-12-31" if end_year.isdigit() else None,
        )

    def _work_to_paper(
        self,
        work: dict[str, Any],
        *,
        include_abstract: bool,
    ) -> dict[str, Any]:
        source_id = self._extract_openalex_id(work.get("id"), "W")
        doi = self._normalize_doi(work.get("doi"))
        doi_url = f"https://doi.org/{doi}" if doi else None
        authors, author_list_truncated = self._authors_from_authorships(
            work.get("authorships")
        )
        abstract = (
            self._reconstruct_abstract(work.get("abstract_inverted_index"))
            if include_abstract
            else None
        )
        paper = dump_jsonable(
            Paper(
                paperId=source_id,
                title=work.get("display_name"),
                abstract=abstract,
                year=work.get("publication_year"),
                authors=authors,
                citationCount=work.get("cited_by_count"),
                referenceCount=work.get("referenced_works_count")
                if isinstance(work.get("referenced_works_count"), int)
                else len(work.get("referenced_works") or [])
                if isinstance(work.get("referenced_works"), list)
                else None,
                influentialCitationCount=None,
                venue=self._venue_from_work(work),
                publicationTypes=work.get("type"),
                publicationDate=work.get("publication_date"),
                url=doi_url or work.get("id"),
                pdfUrl=self._pdf_url_from_work(work),
                source="openalex",
                sourceId=source_id,
                canonicalId=doi or source_id,
                recommendedExpansionId=doi,
                expansionIdStatus="portable" if doi else "not_portable",
            )
        )
        if author_list_truncated:
            paper["authorListTruncated"] = True
        return paper

    @staticmethod
    def _author_profile(author: dict[str, Any]) -> AuthorProfile:
        institutions: list[str] = []
        raw_institutions = author.get("last_known_institutions")
        if isinstance(raw_institutions, list):
            for institution in raw_institutions:
                if not isinstance(institution, dict):
                    continue
                name = institution.get("display_name")
                if isinstance(name, str) and name.strip():
                    institutions.append(name.strip())
        elif isinstance(author.get("last_known_institution"), dict):
            name = author["last_known_institution"].get("display_name")
            if isinstance(name, str) and name.strip():
                institutions.append(name.strip())
        raw_summary_stats = author.get("summary_stats")
        summary_stats: dict[str, Any] = (
            raw_summary_stats if isinstance(raw_summary_stats, dict) else {}
        )
        return AuthorProfile(
            authorId=OpenAlexClient._extract_openalex_id(author.get("id"), "A"),
            name=author.get("display_name"),
            affiliations=institutions,
            homepage=author.get("orcid") or author.get("works_api_url"),
            paperCount=author.get("works_count"),
            citationCount=author.get("cited_by_count"),
            hIndex=summary_stats.get("h_index"),
        )

    async def _lookup_work_raw(self, paper_id: str) -> dict[str, Any]:
        work_id, doi = self._normalize_work_lookup(paper_id)
        if doi:
            response = await self._request(
                "/works",
                params={
                    "filter": f"doi:https://doi.org/{doi}",
                    "per-page": 1,
                    "select": OPENALEX_DETAIL_SELECT,
                },
            )
            results = response.get("results") or []
            if not results:
                raise ValueError(f"No OpenAlex work found for {paper_id!r}.")
            first = results[0]
            if not isinstance(first, dict):
                raise ValueError(f"No OpenAlex work found for {paper_id!r}.")
            return first
        if work_id is None:
            raise ValueError(
                "OpenAlex paper_id must be an OpenAlex W-id, OpenAlex work URL, or DOI."
            )
        response = await self._request(
            f"/works/{work_id}",
            params={"select": OPENALEX_DETAIL_SELECT},
        )
        if not isinstance(response, dict):
            raise ValueError(f"No OpenAlex work found for {paper_id!r}.")
        return response

    async def _batch_get_works(self, work_ids: list[str]) -> list[dict[str, Any]]:
        normalized_ids = [
            work_id
            for raw_id in work_ids
            for work_id in [self._extract_openalex_id(raw_id, "W")]
            if work_id is not None
        ]
        if not normalized_ids:
            return []
        response = await self._request(
            "/works",
            params={
                "filter": f"openalex:{'|'.join(normalized_ids[:100])}",
                "per-page": min(len(normalized_ids), 100),
                "select": OPENALEX_LIST_SELECT,
            },
        )
        results = response.get("results") or []
        normalized_papers = [
            self._work_to_paper(work, include_abstract=False)
            for work in results
            if isinstance(work, dict)
        ]
        papers_by_id = {
            str(paper["sourceId"]): paper
            for paper in normalized_papers
            if paper.get("sourceId") is not None
        }
        return [
            papers_by_id[work_id]
            for work_id in normalized_ids
            if work_id in papers_by_id
        ]

    async def search(
        self,
        query: str,
        limit: int = 10,
        year: Optional[str] = None,
    ) -> dict[str, Any]:
        filters = self._combine_filters(*self._year_filters(year))
        response = await self._request(
            "/works",
            params={
                "search": query.strip(),
                "per-page": min(limit, 200),
                "select": OPENALEX_LIST_SELECT,
                **({"filter": filters} if filters else {}),
            },
        )
        results = response.get("results") or []
        data = [
            self._work_to_paper(work, include_abstract=False)
            for work in results
            if isinstance(work, dict)
        ]
        meta = response.get("meta") if isinstance(response.get("meta"), dict) else {}
        return dump_jsonable(
            {
                "total": meta.get("count", len(data)),
                "offset": 0,
                "data": data,
            }
        )

    async def search_bulk(
        self,
        query: str,
        limit: int = 100,
        cursor: Optional[str] = None,
        year: Optional[str] = None,
    ) -> dict[str, Any]:
        filters = self._combine_filters(*self._year_filters(year))
        response = await self._request(
            "/works",
            params={
                "search": query.strip(),
                "cursor": cursor or "*",
                "per-page": min(limit, 200),
                "select": OPENALEX_LIST_SELECT,
                **({"filter": filters} if filters else {}),
            },
        )
        results = response.get("results") or []
        meta = response.get("meta") if isinstance(response.get("meta"), dict) else {}
        next_cursor = meta.get("next_cursor")
        data = [
            self._work_to_paper(work, include_abstract=False)
            for work in results
            if isinstance(work, dict)
        ]
        return dump_jsonable(
            {
                "total": meta.get("count", len(data)),
                "data": data,
                "pagination": {
                    "hasMore": next_cursor is not None,
                    "nextCursor": next_cursor,
                },
            }
        )

    async def get_paper_details(self, paper_id: str) -> dict[str, Any]:
        work = await self._lookup_work_raw(paper_id)
        return dump_jsonable(self._work_to_paper(work, include_abstract=True))

    async def get_paper_citations(
        self,
        paper_id: str,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        work = await self._lookup_work_raw(paper_id)
        cited_by_api_url = work.get("cited_by_api_url")
        if not isinstance(cited_by_api_url, str) or not cited_by_api_url.strip():
            return {
                "total": 0,
                "offset": 0,
                "data": [],
                "pagination": {"hasMore": False, "nextCursor": None},
            }
        response = await self._request(
            cited_by_api_url,
            params={
                "cursor": cursor or "*",
                "per-page": min(limit, 200),
                "select": OPENALEX_LIST_SELECT,
            },
        )
        meta = response.get("meta") if isinstance(response.get("meta"), dict) else {}
        next_cursor = meta.get("next_cursor")
        results = response.get("results") or []
        data = [
            self._work_to_paper(item, include_abstract=False)
            for item in results
            if isinstance(item, dict)
        ]
        return dump_jsonable(
            {
                "total": meta.get("count", len(data)),
                "offset": 0,
                "data": data,
                "pagination": {
                    "hasMore": next_cursor is not None,
                    "nextCursor": next_cursor,
                },
            }
        )

    async def get_paper_references(
        self,
        paper_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        work = await self._lookup_work_raw(paper_id)
        raw_referenced_works = work.get("referenced_works")
        referenced_works: list[Any] = (
            raw_referenced_works if isinstance(raw_referenced_works, list) else []
        )
        total = len(referenced_works)
        start = max(offset, 0)
        end = min(start + min(limit, 100), total)
        current_ids = referenced_works[start:end]
        papers = await self._batch_get_works(current_ids)
        next_offset = end if end < total else None
        return dump_jsonable(
            {
                "total": total,
                "offset": start,
                "data": papers,
                "pagination": {
                    "hasMore": next_offset is not None,
                    "nextCursor": str(next_offset) if next_offset is not None else None,
                },
            }
        )

    async def search_authors(
        self,
        query: str,
        limit: int = 10,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        response = await self._request(
            "/authors",
            params={
                "search": query.strip(),
                "cursor": cursor or "*",
                "per-page": min(limit, 200),
                "select": OPENALEX_AUTHOR_SELECT,
            },
        )
        meta = response.get("meta") if isinstance(response.get("meta"), dict) else {}
        next_cursor = meta.get("next_cursor")
        results = response.get("results") or []
        data = [
            self._author_profile(author)
            for author in results
            if isinstance(author, dict)
        ]
        return dump_jsonable(
            {
                "total": meta.get("count", len(data)),
                "offset": 0,
                "data": data,
                "pagination": {
                    "hasMore": next_cursor is not None,
                    "nextCursor": next_cursor,
                },
            }
        )

    async def get_author_info(self, author_id: str) -> dict[str, Any]:
        normalized_author_id = self._normalize_author_id(author_id)
        response = await self._request(
            f"/authors/{normalized_author_id}",
            params={"select": OPENALEX_AUTHOR_SELECT},
        )
        if not isinstance(response, dict):
            raise ValueError(f"No OpenAlex author found for {author_id!r}.")
        return dump_jsonable(self._author_profile(response))

    async def get_author_papers(
        self,
        author_id: str,
        limit: int = 100,
        cursor: Optional[str] = None,
        year: Optional[str] = None,
    ) -> dict[str, Any]:
        normalized_author_id = self._normalize_author_id(author_id)
        filters = self._combine_filters(
            f"authorships.author.id:{normalized_author_id}",
            *self._year_filters(year),
        )
        response = await self._request(
            "/works",
            params={
                "filter": filters,
                "cursor": cursor or "*",
                "per-page": min(limit, 200),
                "select": OPENALEX_LIST_SELECT,
            },
        )
        meta = response.get("meta") if isinstance(response.get("meta"), dict) else {}
        next_cursor = meta.get("next_cursor")
        results = response.get("results") or []
        data = [
            self._work_to_paper(work, include_abstract=False)
            for work in results
            if isinstance(work, dict)
        ]
        return dump_jsonable(
            {
                "total": meta.get("count", len(data)),
                "offset": 0,
                "data": data,
                "pagination": {
                    "hasMore": next_cursor is not None,
                    "nextCursor": next_cursor,
                },
            }
        )
