"""CORE API client."""

import logging
from typing import Any, Optional

from ...constants import CORE_API_BASE
from ...models import Author, CoreSearchResponse, Paper, dump_jsonable
from ...transport import httpx

logger = logging.getLogger("scholar-search-mcp")


class CoreApiClient:
    """CORE API v3 client (https://api.core.ac.uk/docs/v3)."""

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key
        self.timeout = timeout

    async def search(
        self,
        query: str,
        limit: int = 10,
        start: int = 0,
        year: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Search CORE. Returns shape compatible with merge: list of normalized
        paper dicts and total. Works without API key (subject to rate limits);
        with key you get higher limits.
        """
        params: dict[str, Any] = {
            "q": query.strip(),
            "limit": min(limit, 100),
            "offset": start,
        }
        if year:
            if "-" in year:
                year_start, year_end = year.split("-", maxsplit=1)
                year_start = year_start.strip()[:4]
                year_end = year_end.strip()[:4]
                if year_start.isdigit() and year_end.isdigit():
                    params["q"] = (
                        f"{params['q']} yearPublished:[{year_start} TO {year_end}]"
                    )
            else:
                single_year = year.strip()[:4]
                if single_year.isdigit():
                    params["q"] = f"{params['q']} yearPublished:{single_year}"

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    CORE_API_BASE,
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
        except Exception as exc:
            logger.warning("CORE search request failed: %s", exc)
            raise

        data = response.json()
        results = data.get("results") or []
        entries: list[Paper] = []
        for result in results:
            paper = self._result_to_paper(result)
            if paper:
                entries.append(Paper.model_validate(paper))
        if results and len(entries) < len(results):
            logger.debug(
                "CORE returned %s results, %s had valid url/title "
                "(some may lack doi/downloadUrl)",
                len(results),
                len(entries),
            )
        return dump_jsonable(
              CoreSearchResponse(
                 total=data.get("total_hits", len(entries)),
                 entries=entries,
              )
        )

    def _result_to_paper(self, result: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Convert one CORE result to an S2-compatible paper dict."""
        title = (result.get("title") or "").strip()
        if not title:
            return None

        url: Optional[str] = None
        if result.get("doi"):
            url = f"https://doi.org/{result['doi']}"
        if not url and result.get("downloadUrl"):
            download_url = result["downloadUrl"]
            if isinstance(download_url, str):
                url = download_url
            elif isinstance(download_url, dict):
                url = download_url.get("url") or download_url.get("link")
                if (
                    not url
                    and isinstance(download_url.get("urls"), list)
                    and download_url["urls"]
                ):
                    first_url = download_url["urls"][0]
                    if isinstance(first_url, str):
                        url = first_url
                    elif isinstance(first_url, dict):
                        url = first_url.get("url") or first_url.get("link")
        if not url and result.get("sourceFulltextUrls"):
            source_urls = result["sourceFulltextUrls"]
            if isinstance(source_urls, str):
                url = source_urls
            elif isinstance(source_urls, list) and source_urls:
                first_source_url = source_urls[0]
                if isinstance(first_source_url, str):
                    url = first_source_url
                elif isinstance(first_source_url, dict):
                    url = first_source_url.get("url") or first_source_url.get("link")
            elif isinstance(source_urls, dict):
                urls = (
                    source_urls.get("urls")
                    or source_urls.get("url")
                    or source_urls.get("link")
                )
                if isinstance(urls, list) and urls:
                    url = urls[0]
                elif isinstance(urls, str):
                    url = urls
        if not url and result.get("id") is not None:
            url = f"https://core.ac.uk/works/{result['id']}"
        if not url:
            return None

        raw_date = result.get("publishedDate") or result.get("depositedDate")
        year_val: Optional[int] = None
        date_str: Optional[str] = None
        if raw_date:
            if isinstance(raw_date, str):
                date_str = raw_date
                if len(raw_date) >= 4:
                    try:
                        year_val = int(raw_date[:4])
                    except ValueError:
                        pass
            elif hasattr(raw_date, "year"):
                year_val = getattr(raw_date, "year", None)
                date_str = str(raw_date)

        authors: list[Author] = []
        for author in result.get("authors") or []:
            if isinstance(author, dict):
                name = author.get("name")
            elif isinstance(author, str):
                name = author
            else:
                name = None
            if name:
                authors.append(Author(name=name))

        pdf_url = result.get("downloadUrl")
        if isinstance(pdf_url, dict):
            pdf_url = pdf_url.get("url") if pdf_url else None
        if not pdf_url and result.get("sourceFulltextUrls"):
            source_urls = result["sourceFulltextUrls"]
            if isinstance(source_urls, list) and source_urls:
                pdf_url = source_urls[0]
            elif isinstance(source_urls, str):
                pdf_url = source_urls

        venue = ", ".join(
            journal.get("title", "")
            for journal in (result.get("journals") or [])
            if isinstance(journal, dict) and journal.get("title")
        )

        return dump_jsonable(
            Paper(
                paperId=str(result.get("id", result.get("doi", ""))),
                title=title,
                abstract=(result.get("abstract") or result.get("fullText") or "")[:5000]
                or None,
                year=year_val,
                authors=authors,
                citationCount=result.get("citationCount"),
                referenceCount=None,
                influentialCitationCount=None,
                venue=venue or None,
                publicationTypes=result.get("documentType"),
                publicationDate=date_str,
                url=url,
                pdfUrl=pdf_url,
                source="core",
            )
        )
