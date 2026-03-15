"""Search fallback and result-shaping helpers."""

import logging
from collections.abc import Sequence
from typing import Any, Optional

from .clients.serpapi import SerpApiKeyMissingError
from .models import (
    ArxivSearchResponse,
    BrokerAttempt,
    BrokerMetadata,
    CoreSearchResponse,
    Paper,
    SearchResponse,
    SemanticSearchResponse,
)
from .models.tools import (
    DEFAULT_SEARCH_PROVIDER_ORDER,
    SearchPapersArgs,
    SearchProvider,
)

logger = logging.getLogger("scholar-search-mcp")

SEMANTIC_SCHOLAR_ONLY_FIELDS = (
    "publication_date_or_year",
    "fields_of_study",
    "publication_types",
    "open_access_pdf",
    "min_citation_count",
)
SEMANTIC_SCHOLAR_ONLY_FILTER_ALIASES = {
    field_name: SearchPapersArgs.model_fields[field_name].alias or field_name
    for field_name in SEMANTIC_SCHOLAR_ONLY_FIELDS
}


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


def _metadata(
    *,
    provider_used: str,
    attempts: list[BrokerAttempt],
    ss_only_filters: list[str],
) -> BrokerMetadata:
    """Build consistent broker metadata for ``search_papers`` responses."""
    return BrokerMetadata(
        provider_used=provider_used,
        attempted_providers=attempts,
        semantic_scholar_only_filters=ss_only_filters,
    )


def _effective_provider_order(
    *,
    preferred_provider: SearchProvider | None,
    provider_order: Sequence[SearchProvider] | None,
) -> list[SearchProvider]:
    order = list(provider_order or DEFAULT_SEARCH_PROVIDER_ORDER)
    if preferred_provider is None:
        return order
    return [preferred_provider] + [
        provider for provider in order if provider != preferred_provider
    ]


def _skip_for_ss_only_filters(
    provider: SearchProvider, ss_only_filters: list[str]
) -> BrokerAttempt | None:
    if provider not in {"core", "serpapi_google_scholar"} or not ss_only_filters:
        return None
    return BrokerAttempt(
        provider=provider,
        status="skipped",
        reason=(
            "Skipped because Semantic Scholar-only filters were requested: "
            + ", ".join(ss_only_filters)
        ),
    )


def _disabled_provider_attempt(provider: SearchProvider) -> BrokerAttempt:
    disabled_reasons = {
        "core": "Disabled by SCHOLAR_SEARCH_ENABLE_CORE=false.",
        "semantic_scholar": "Disabled by SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR=false.",
        "serpapi_google_scholar": "Disabled by SCHOLAR_SEARCH_ENABLE_SERPAPI=false.",
        "arxiv": "Disabled by SCHOLAR_SEARCH_ENABLE_ARXIV=false.",
    }
    return BrokerAttempt(
        provider=provider,
        status="skipped",
        reason=disabled_reasons[provider],
    )


def _earlier_result_attempt(provider: SearchProvider) -> BrokerAttempt:
    return BrokerAttempt(
        provider=provider,
        status="skipped",
        reason="Skipped because an earlier provider already returned results.",
    )


def _core_result(core_response: dict[str, Any], limit: int) -> SearchResponse:
    core_search = CoreSearchResponse.model_validate(core_response)
    return SearchResponse(
        total=core_search.total or len(core_search.entries),
        offset=0,
        data=core_search.entries[:limit],
    )


def _semantic_result(s2_response: dict[str, Any], limit: int) -> SearchResponse:
    semantic_search = SemanticSearchResponse.model_validate(s2_response)
    return SearchResponse(
        total=semantic_search.total or len(semantic_search.data),
        offset=semantic_search.offset,
        data=[_enrich_ss_paper(paper) for paper in semantic_search.data[:limit]],
    )


def _serpapi_result(serpapi_papers: list[dict[str, Any]], limit: int) -> SearchResponse:
    validated: list[Paper] = [Paper.model_validate(p) for p in serpapi_papers]
    return SearchResponse(
        total=len(validated),
        offset=0,
        data=validated[:limit],
    )


def _arxiv_result(arxiv_response: dict[str, Any], limit: int) -> SearchResponse:
    arxiv_search = ArxivSearchResponse.model_validate(arxiv_response)
    return SearchResponse(
        total=arxiv_search.total_results,
        offset=0,
        data=arxiv_search.entries[:limit],
    )


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
    preferred_provider: SearchProvider | None = None,
    provider_order: Sequence[SearchProvider] | None = None,
) -> dict[str, Any]:
    """Execute the search broker chain using the configured provider order.

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
    ss_only_filters = [
        SEMANTIC_SCHOLAR_ONLY_FILTER_ALIASES[field_name]
        for field_name, value in (
            ("publication_date_or_year", publication_date_or_year),
            ("fields_of_study", fields_of_study),
            ("publication_types", publication_types),
            ("open_access_pdf", open_access_pdf),
            ("min_citation_count", min_citation_count),
        )
        if value is not None
    ]
    effective_order = _effective_provider_order(
        preferred_provider=preferred_provider,
        provider_order=provider_order,
    )

    result: SearchResponse | None = None
    provider_used = "none"
    attempts: list[BrokerAttempt] = []
    processed_providers = 0
    for index, provider in enumerate(effective_order):
        processed_providers = index + 1
        skip_for_filters = _skip_for_ss_only_filters(provider, ss_only_filters)
        if skip_for_filters is not None:
            attempts.append(skip_for_filters)
            continue

        if provider == "core":
            if not enable_core:
                attempts.append(_disabled_provider_attempt(provider))
                continue
            try:
                core_response = await core_client.search(
                    query=query,
                    limit=limit,
                    start=0,
                    year=year,
                )
                result = _core_result(core_response, limit)
                if result.data:
                    provider_used = provider
                    attempts.append(
                        BrokerAttempt(provider=provider, status="returned_results")
                    )
                    logger.info("search_papers: using CORE API results")
                    break
                attempts.append(
                    BrokerAttempt(provider=provider, status="returned_no_results")
                )
                result = None
            except Exception as exc:
                attempts.append(
                    BrokerAttempt(provider=provider, status="failed", reason=str(exc))
                )
                logger.info(
                    "search_papers: CORE failed (%s), falling back to next channel",
                    exc,
                )
                result = None
            continue

        if provider == "semantic_scholar":
            if not enable_semantic_scholar:
                attempts.append(_disabled_provider_attempt(provider))
                continue
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
                result = _semantic_result(s2_response, limit)
                if result.data:
                    provider_used = provider
                    attempts.append(
                        BrokerAttempt(provider=provider, status="returned_results")
                    )
                    logger.info("search_papers: using Semantic Scholar results")
                    break
                attempts.append(
                    BrokerAttempt(provider=provider, status="returned_no_results")
                )
                result = None
            except Exception as exc:
                attempts.append(
                    BrokerAttempt(provider=provider, status="failed", reason=str(exc))
                )
                logger.info(
                    "search_papers: Semantic Scholar failed (%s), "
                    "falling back to next channel",
                    exc,
                )
                result = None
            continue

        if provider == "serpapi_google_scholar":
            if not enable_serpapi:
                attempts.append(_disabled_provider_attempt(provider))
                continue
            if serpapi_client is None:
                attempts.append(
                    BrokerAttempt(
                        provider=provider,
                        status="skipped",
                        reason="Enabled but no SerpApi client is configured.",
                    )
                )
                continue
            try:
                serpapi_papers = await serpapi_client.search(
                    query=query,
                    limit=limit,
                    year=year,
                )
                result = _serpapi_result(serpapi_papers, limit)
                if result.data:
                    provider_used = provider
                    attempts.append(
                        BrokerAttempt(provider=provider, status="returned_results")
                    )
                    logger.info("search_papers: using SerpApi Google Scholar results")
                    break
                attempts.append(
                    BrokerAttempt(provider=provider, status="returned_no_results")
                )
                result = None
            except SerpApiKeyMissingError:
                raise
            except Exception as exc:
                attempts.append(
                    BrokerAttempt(provider=provider, status="failed", reason=str(exc))
                )
                logger.info(
                    "search_papers: SerpApi failed (%s), falling back to next channel",
                    exc,
                )
                result = None
            continue

        if not enable_arxiv:
            attempts.append(_disabled_provider_attempt(provider))
            continue

        arxiv_response = await arxiv_client.search(
            query=query,
            limit=limit,
            year=year,
        )
        result = _arxiv_result(arxiv_response, limit)
        if result.data:
            provider_used = provider
            attempts.append(BrokerAttempt(provider=provider, status="returned_results"))
            logger.info("search_papers: using arXiv results")
            break
        attempts.append(BrokerAttempt(provider=provider, status="returned_no_results"))
        result = None

    if provider_used != "none":
        attempts.extend(
            _earlier_result_attempt(provider)
            for provider in effective_order[processed_providers:]
        )
        if result is not None:
            result.broker_metadata = _metadata(
                provider_used=provider_used,
                attempts=attempts,
                ss_only_filters=ss_only_filters,
            )

    if result is None:
        return _dump_search_response(
            SearchResponse(
                broker_metadata=_metadata(
                    provider_used="none",
                    attempts=attempts,
                    ss_only_filters=ss_only_filters,
                ),
            )
        )
    return _dump_search_response(result)
