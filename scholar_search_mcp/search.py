"""Search fallback and result-shaping helpers."""

import logging
from typing import Any, Optional

from .models import (
    ArxivSearchResponse,
    CoreSearchResponse,
    SearchResponse,
    SemanticSearchResponse,
)

logger = logging.getLogger("scholar-search-mcp")


def _dump_search_response(response: SearchResponse) -> dict[str, Any]:
    return {
        "total": response.total,
        "offset": response.offset,
        "data": [
            paper.model_dump(by_alias=True, exclude_none=True, exclude_defaults=True)
            for paper in response.data
        ],
    }


def _merge_search_results(
    s2_response: dict[str, Any],
    arxiv_response: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    """Merge Semantic Scholar and arXiv results into the shared response shape."""
    semantic_search = SemanticSearchResponse.model_validate(s2_response)
    arxiv_search = ArxivSearchResponse.model_validate(arxiv_response)

    s2_data = [
        paper.model_copy(update={"source": paper.source or "semantic_scholar"})
        for paper in semantic_search.data
    ]
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
    core_client: Any,
    semantic_client: Any,
    arxiv_client: Any,
) -> dict[str, Any]:
    """Execute the CORE -> Semantic Scholar -> arXiv search fallback chain."""
    result: SearchResponse | None = None
    if enable_core:
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
            )
            semantic_search = SemanticSearchResponse.model_validate(s2_response)
            if semantic_search.data:
                result = SearchResponse(
                    total=semantic_search.total or len(semantic_search.data),
                    offset=semantic_search.offset,
                    data=[
                        paper.model_copy(
                            update={"source": paper.source or "semantic_scholar"}
                        )
                        for paper in semantic_search.data[:limit]
                    ],
                )
                logger.info("search_papers: using Semantic Scholar results")
        except Exception as exc:
            logger.info(
                "search_papers: Semantic Scholar failed (%s), "
                "falling back to next channel",
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
            )
            logger.info("search_papers: using arXiv results")

    if result is None:
        return _dump_search_response(SearchResponse())
    return _dump_search_response(result)
