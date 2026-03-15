"""Search fallback and result-shaping helpers."""

import logging
from typing import Any, Optional

from .clients.serpapi import SerpApiKeyMissingError
from .models import (
    ArxivSearchResponse,
    BrokerMetadata,
    CoreSearchResponse,
    Paper,
    SearchResponse,
    SemanticSearchResponse,
)

logger = logging.getLogger("scholar-search-mcp")


def _enrich_ss_paper(paper: Paper) -> Paper:
    """Return a copy of a Semantic Scholar paper enriched with provenance fields.

    ``sourceId`` is the Semantic Scholar-native ``paperId`` hash.
    ``canonicalId`` follows the documented priority order:
    DOI > paperId > arXiv ID > sourceId.
    """
    external_ids: dict[str, Any] = (paper.model_extra or {}).get("externalIds") or {}
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
        }
    )


def _dump_search_response(response: SearchResponse) -> dict[str, Any]:
    result: dict[str, Any] = {
        "total": response.total,
        "offset": response.offset,
        "data": [
            paper.model_dump(by_alias=True, exclude_none=True, exclude_defaults=True)
            for paper in response.data
        ],
    }
    if response.broker_metadata is not None:
        result["brokerMetadata"] = response.broker_metadata.model_dump(by_alias=True)
    return result


def _merge_search_results(
    s2_response: dict[str, Any],
    arxiv_response: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    """Merge Semantic Scholar and arXiv results into the shared response shape."""
    semantic_search = SemanticSearchResponse.model_validate(s2_response)
    arxiv_search = ArxivSearchResponse.model_validate(arxiv_response)

    s2_data = [_enrich_ss_paper(paper) for paper in semantic_search.data]
    arxiv_entries = list(arxiv_search.entries)

    seen_arxiv_ids = set()
    for paper in s2_data:
        external_ids = (paper.model_extra or {}).get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv")
        if arxiv_id:
            seen_arxiv_ids.add(str(arxiv_id))

    merged = list(s2_data)
    for paper in arxiv_entries:
        arxiv_id = paper.paper_id or ""
        if arxiv_id and arxiv_id not in seen_arxiv_ids:
            seen_arxiv_ids.add(arxiv_id)
            merged.append(paper)

    return _dump_search_response(
        SearchResponse(
            total=len(merged[:limit]),
            offset=semantic_search.offset,
            data=merged[:limit],
        )
    )


def _core_response_to_merged(
    core_response: dict[str, Any], limit: int
) -> dict[str, Any]:
    """Convert CORE search response to unified shape (total, offset, data)."""
    core_search = CoreSearchResponse.model_validate(core_response)
    return _dump_search_response(
        SearchResponse(
            total=core_search.total or len(core_search.entries),
            offset=0,
            data=core_search.entries[:limit],
        )
    )


async def search_papers_with_fallback(
    *,
    query: str,
    limit: int,
    year: Optional[str],
    fields: Optional[list[str]],
    venue: Optional[list[str]],
    enable_core: bool,
    enable_semantic_scholar: bool,
    enable_arxiv: bool,
    enable_serpapi: bool = False,
    core_client: Any,
    semantic_client: Any,
    arxiv_client: Any,
    serpapi_client: Any = None,
    publication_date_or_year: Optional[str] = None,
    fields_of_study: Optional[str] = None,
    publication_types: Optional[str] = None,
    open_access_pdf: Optional[bool] = None,
    min_citation_count: Optional[int] = None,
) -> dict[str, Any]:
    """Execute the CORE -> Semantic Scholar -> SerpApi -> arXiv search fallback chain.

    CORE is skipped when any Semantic Scholar-only filter is requested
    (``publicationDateOrYear``, ``fieldsOfStudy``, ``publicationTypes``,
    ``openAccessPdf``, ``minCitationCount``) because CORE does not support those
    parameters, and silently returning un-filtered CORE results would violate the
    caller's intent.

    SerpApi Google Scholar is included in the fallback chain when
    ``enable_serpapi=True`` (opt-in, paid API).  It is also skipped when any
    Semantic Scholar-only filter is requested, because those filters have no
    equivalent in Google Scholar.

    Pagination is intentionally not supported here: each provider uses a different
    continuation mechanism and mixing pages from different backends would produce
    incorrect results.  For paginated retrieval use ``search_papers_bulk``
    (Semantic Scholar) or other provider-specific tools.
    """
    has_ss_only_filter = any(
        (
            publication_date_or_year is not None,
            fields_of_study is not None,
            publication_types is not None,
            open_access_pdf is not None,
            min_citation_count is not None,
        )
    )

    result: SearchResponse | None = None
    if enable_core and not has_ss_only_filter:
        try:
            core_response = await core_client.search(
                query=query,
                limit=limit,
                start=0,
                year=year,
            )
            core_search = CoreSearchResponse.model_validate(core_response)
            if core_search.entries:
                result = SearchResponse(
                    total=core_search.total or len(core_search.entries),
                    offset=0,
                    data=core_search.entries[:limit],
                    broker_metadata=BrokerMetadata(provider_used="core"),
                )
                logger.info("search_papers: using CORE API results")
        except Exception as exc:
            logger.info(
                "search_papers: CORE failed (%s), falling back to next channel",
                exc,
            )

    if result is None and enable_semantic_scholar:
        try:
            s2_response = await semantic_client.search_papers(
                query=query,
                limit=limit,
                fields=fields,
                year=year,
                venue=venue,
                publication_date_or_year=publication_date_or_year,
                fields_of_study=fields_of_study,
                publication_types=publication_types,
                open_access_pdf=open_access_pdf,
                min_citation_count=min_citation_count,
            )
            semantic_search = SemanticSearchResponse.model_validate(s2_response)
            if semantic_search.data:
                result = SearchResponse(
                    total=semantic_search.total or len(semantic_search.data),
                    offset=semantic_search.offset,
                    data=[
                        _enrich_ss_paper(paper)
                        for paper in semantic_search.data[:limit]
                    ],
                    broker_metadata=BrokerMetadata(provider_used="semantic_scholar"),
                )
                logger.info("search_papers: using Semantic Scholar results")
        except Exception as exc:
            logger.info(
                "search_papers: Semantic Scholar failed (%s), "
                "falling back to next channel",
                exc,
            )

    if result is None and enable_serpapi and serpapi_client is not None and (
        not has_ss_only_filter
    ):
        try:
            serpapi_papers = await serpapi_client.search(
                query=query,
                limit=limit,
                year=year,
            )
            if serpapi_papers:
                validated: list[Paper] = [
                    Paper.model_validate(p) for p in serpapi_papers
                ]
                result = SearchResponse(
                    total=len(validated),
                    offset=0,
                    data=validated[:limit],
                    broker_metadata=BrokerMetadata(
                        provider_used="serpapi_google_scholar"
                    ),
                )
                logger.info("search_papers: using SerpApi Google Scholar results")
        except SerpApiKeyMissingError:
            # Config/auth errors are not transient — re-raise so the caller
            # gets an actionable error instead of silently falling back to arXiv.
            raise
        except Exception as exc:
            logger.info(
                "search_papers: SerpApi failed (%s), falling back to arXiv",
                exc,
            )

    if result is None and enable_arxiv:
        arxiv_response = await arxiv_client.search(
            query=query,
            limit=limit,
            year=year,
        )
        arxiv_search = ArxivSearchResponse.model_validate(arxiv_response)
        if arxiv_search.entries:
            result = SearchResponse(
                total=arxiv_search.total_results,
                offset=0,
                data=arxiv_search.entries[:limit],
                broker_metadata=BrokerMetadata(provider_used="arxiv"),
            )
            logger.info("search_papers: using arXiv results")

    if result is None:
        return _dump_search_response(
            SearchResponse(
                broker_metadata=BrokerMetadata(provider_used="none"),
            )
        )
    return _dump_search_response(result)
