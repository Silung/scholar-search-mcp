"""arXiv API client."""

import logging
from typing import Any, Optional
from urllib.parse import quote_plus

from defusedxml import ElementTree as ET

from ...constants import ARXIV_API_BASE, ARXIV_NS, ATOM_NS, OPENSEARCH_NS
from ...models import ArxivSearchResponse, Author, Paper, dump_jsonable
from ...parsing import _arxiv_id_from_url, _text
from ...transport import httpx

logger = logging.getLogger("scholar-search-mcp")


class ArxivClient:
    """arXiv API client (https://info.arxiv.org/help/api/user-manual.html)."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def search(
        self,
        query: str,
        limit: int = 10,
        start: int = 0,
        year: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Search arXiv. Returns shape compatible with merge: list of normalized
        paper dicts and totalResults.
        """
        search_query = f"all:{query.strip()}"
        params: dict[str, Any] = {
            "search_query": search_query,
            "start": start,
            "max_results": min(limit, 2000),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        if year:
            if "-" in year:
                year_start, year_end = year.split("-", maxsplit=1)
                year_start = year_start.strip()[:4]
                year_end = year_end.strip()[:4]
                if year_start.isdigit() and year_end.isdigit():
                    params["search_query"] = (
                        f"{params['search_query']}+AND+submittedDate:"
                        f"[{year_start}01010000+TO+{year_end}12312359]"
                    )
            else:
                single_year = year.strip()[:4]
                if single_year.isdigit():
                    params["search_query"] = (
                        f"{params['search_query']}+AND+submittedDate:"
                        f"[{single_year}01010000+TO+{single_year}12312359]"
                    )

        url = (
            f"{ARXIV_API_BASE}?search_query={quote_plus(params['search_query'])}"
            f"&start={params['start']}&max_results={params['max_results']}"
            f"&sortBy={params['sortBy']}&sortOrder={params['sortOrder']}"
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
        except Exception as exc:
            logger.warning("arXiv search failed: %s", exc)
            return dump_jsonable(ArxivSearchResponse())

        root = ET.fromstring(response.text)
        total_el = root.find(f"{{{OPENSEARCH_NS}}}totalResults")
        total_results = int(_text(total_el)) if total_el is not None else 0

        entries: list[Paper] = []
        for entry in root.findall(f"{{{ATOM_NS}}}entry"):
            summary_el = entry.find(f"{{{ATOM_NS}}}summary")
            title_text = _text(entry.find(f"{{{ATOM_NS}}}title")).lower()
            if summary_el is not None and title_text == "error":
                continue
            paper = self._entry_to_paper(entry)
            if paper:
                entries.append(Paper.model_validate(paper))
        return dump_jsonable(
            ArxivSearchResponse(totalResults=total_results, entries=entries)
        )

    def _entry_to_paper(self, entry: Any) -> Optional[dict[str, Any]]:
        """Convert one Atom entry to an S2-compatible paper dict."""
        id_el = entry.find(f"{{{ATOM_NS}}}id")
        id_url = _text(id_el) if id_el is not None else ""
        arxiv_id = _arxiv_id_from_url(id_url)
        if not arxiv_id:
            return None

        title_el = entry.find(f"{{{ATOM_NS}}}title")
        title = _text(title_el).replace("\n", " ").strip()

        summary_el = entry.find(f"{{{ATOM_NS}}}summary")
        abstract = (
            _text(summary_el).replace("\n", " ").strip()
            if summary_el is not None
            else ""
        )

        published_el = entry.find(f"{{{ATOM_NS}}}published")
        updated_el = entry.find(f"{{{ATOM_NS}}}updated")
        date_str = _text(published_el) or _text(updated_el)
        year_val: Optional[int] = None
        if date_str and len(date_str) >= 4:
            try:
                year_val = int(date_str[:4])
            except ValueError:
                pass

        authors = []
        for author in entry.findall(f"{{{ATOM_NS}}}author"):
            name_el = author.find(f"{{{ATOM_NS}}}name")
            name = _text(name_el) if name_el is not None else ""
            if name:
                authors.append(Author(name=name))

        link_alternate = None
        link_pdf = None
        for link in entry.findall(f"{{{ATOM_NS}}}link"):
            href = link.get("href") or ""
            rel = link.get("rel") or ""
            title_attr = (link.get("title") or "").lower()
            if rel == "alternate":
                link_alternate = href
            elif "pdf" in title_attr or (rel == "related" and "pdf" in href):
                link_pdf = href

        primary_cat = entry.find(f"{{{ARXIV_NS}}}primary_category")
        venue = primary_cat.get("term") if primary_cat is not None else None

        return dump_jsonable(
            Paper(
                paperId=arxiv_id,
                title=title,
                abstract=abstract or None,
                year=year_val,
                authors=authors,
                citationCount=None,
                referenceCount=None,
                influentialCitationCount=None,
                venue=venue,
                publicationTypes=None,
                publicationDate=date_str or None,
                url=link_alternate or f"https://arxiv.org/abs/{arxiv_id}",
                pdfUrl=link_pdf,
                source="arxiv",
            )
        )
