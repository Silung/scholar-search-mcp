"""Normalize SerpApi Google Scholar organic results into the shared Paper model."""

import re
from typing import Any, Optional

from ...models import Author, Paper, dump_jsonable


def _extract_year_from_summary(summary: str) -> Optional[int]:
    """Extract the first 4-digit year (1900-2099) from a publication summary."""
    match = re.search(r"\b(19|20)\d{2}\b", summary)
    if match:
        try:
            return int(match.group())
        except ValueError:
            pass
    return None


def _extract_doi_from_link(link: str) -> Optional[str]:
    """Try to extract a DOI from a URL string."""
    match = re.search(r"10\.\d{4,9}/\S+", link)
    return match.group(0).rstrip(".,;)") if match else None


def _parse_year_range(year: str) -> tuple[Optional[int], Optional[int]]:
    """Parse a year or year-range string into (low, high) integer pair.

    Accepts ``"2023"`` (single year), ``"2020-2023"`` (inclusive range), and
    open-ended variants like ``"2020-"`` or ``"-2023"``.
    """
    year = year.strip()
    if "-" in year:
        parts = year.split("-", 1)
        low_str, high_str = parts[0].strip(), parts[1].strip()
        year_low: Optional[int] = None
        year_high: Optional[int] = None
        if len(low_str) >= 4 and low_str[:4].isdigit():
            try:
                year_low = int(low_str[:4])
            except ValueError:
                pass
        if len(high_str) >= 4 and high_str[:4].isdigit():
            try:
                year_high = int(high_str[:4])
            except ValueError:
                pass
        return year_low, year_high
    else:
        if len(year) >= 4 and year[:4].isdigit():
            try:
                y = int(year[:4])
                return y, y
            except ValueError:
                pass
    return None, None


def normalize_organic_result(result: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Convert one SerpApi organic Scholar result to a normalized paper dict.

    Returns a ``dump_jsonable``-serialized dict compatible with ``Paper``, or
    ``None`` if the result lacks a title (minimum required field).
    """
    title = (result.get("title") or "").strip()
    if not title:
        return None

    # --- Provider identifiers ---
    result_id: Optional[str] = result.get("result_id") or None
    inline_links: dict[str, Any] = result.get("inline_links") or {}

    versions: dict[str, Any] = inline_links.get("versions") or {}
    cluster_id: Optional[str] = str(versions["cluster_id"]) if versions.get(
        "cluster_id"
    ) else None

    cited_by: dict[str, Any] = inline_links.get("cited_by") or {}
    cites_id: Optional[str] = str(cited_by["cites_id"]) if cited_by.get(
        "cites_id"
    ) else None

    # sourceId priority: result_id > cluster_id > cites_id
    source_id: Optional[str] = result_id or cluster_id or cites_id

    # --- URL and DOI ---
    link: Optional[str] = result.get("link") or None
    doi: Optional[str] = None
    if link:
        doi = _extract_doi_from_link(link)

    # canonicalId priority: DOI > cluster_id > result_id > sourceId
    canonical_id: Optional[str] = doi or cluster_id or result_id or source_id

    # --- Authors ---
    authors: list[Author] = []
    pub_info: dict[str, Any] = result.get("publication_info") or {}
    for author in pub_info.get("authors") or []:
        if isinstance(author, dict):
            name = (author.get("name") or "").strip()
            if name:
                authors.append(Author(name=name))

    # --- Year and venue from publication_info.summary ---
    year: Optional[int] = None
    venue: Optional[str] = None
    summary: str = (pub_info.get("summary") or "").strip()
    if summary:
        year = _extract_year_from_summary(summary)
        # Summaries look like "Author Names - Journal Name, 2023" or
        # "Journal Name, 2023". Extract the venue-ish component.
        summary_parts = summary.split(" - ", 1)
        venue_part = summary_parts[-1].strip() if len(summary_parts) > 1 else ""
        if not venue_part:
            venue_part = summary_parts[0].strip()
        # Strip trailing year / comma from venue
        venue_candidate = re.sub(r",?\s*(19|20)\d{2}.*$", "", venue_part).strip()
        if venue_candidate and venue_candidate != summary.strip():
            venue = venue_candidate or None

    # --- Abstract/snippet: Scholar snippet is excerpt, not a full abstract ---
    abstract: Optional[str] = (result.get("snippet") or "").strip() or None

    # --- PDF URL from resources ---
    pdf_url: Optional[str] = None
    for resource in result.get("resources") or []:
        if isinstance(resource, dict):
            fmt = (resource.get("file_format") or "").lower()
            res_title = (resource.get("title") or "").lower()
            res_link = resource.get("link") or ""
            if res_link and ("pdf" in fmt or "pdf" in res_title):
                pdf_url = res_link
                break

    # --- Citation count ---
    citation_count: Optional[int] = None
    cited_by_total = cited_by.get("total")
    if cited_by_total is not None:
        try:
            citation_count = int(cited_by_total)
        except (ValueError, TypeError):
            pass

    paper = Paper(
        paperId=result_id,
        title=title,
        abstract=abstract,
        year=year,
        authors=authors,
        citationCount=citation_count,
        referenceCount=None,
        influentialCitationCount=None,
        venue=venue,
        publicationTypes=None,
        publicationDate=None,
        url=link,
        pdfUrl=pdf_url,
        source="serpapi_google_scholar",
        sourceId=source_id,
        canonicalId=canonical_id,
        scholarResultId=result_id,
    )
    # Preserve supplementary Scholar cluster/cite identifiers as extras for
    # any downstream tool that may need them in the future.
    extra: dict[str, Any] = {}
    if cluster_id:
        extra["scholarClusterId"] = cluster_id
    if cites_id:
        extra["scholarCitesId"] = cites_id
    if extra:
        paper = paper.model_copy(update=extra)

    return dump_jsonable(paper)
