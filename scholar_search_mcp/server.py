"""Scholar Search MCP Server - Semantic Scholar API via Model Context Protocol."""

import asyncio
import io
import json
import logging
import os
import re
import shutil
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote_plus

from typing import Any, Optional

import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scholar-search-mcp")

API_BASE_URL = "https://api.semanticscholar.org/graph/v1"
CORE_API_BASE = "https://api.core.ac.uk/v3/search/works"
ARXIV_API_BASE = "https://export.arxiv.org/api/query"
ARXIV_SRC_BASE = "https://arxiv.org/src"

# 429 时先多尝试几次，再用指数退避
MAX_429_RETRIES = 6

# Atom/arXiv XML namespaces
ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"

DEFAULT_PAPER_FIELDS = [
    "paperId",
    "title",
    "abstract",
    "year",
    "authors",
    "citationCount",
    "referenceCount",
    "influentialCitationCount",
    "venue",
    "publicationTypes",
    "publicationDate",
    "url",
]

DEFAULT_AUTHOR_FIELDS = [
    "authorId",
    "name",
    "affiliations",
    "homepage",
    "paperCount",
    "citationCount",
    "hIndex",
]


def _arxiv_id_from_url(id_url: str) -> str:
    """Extract arXiv id from abs URL, e.g. http://arxiv.org/abs/2201.00978v1 -> 2201.00978."""
    if not id_url:
        return ""
    m = re.search(r"arxiv\.org/abs/([\w.-]+)", id_url, re.I)
    if not m:
        return id_url
    raw = m.group(1)
    return re.sub(r"v\d+$", "", raw)  # strip version


def _normalize_arxiv_source_id(raw: str) -> str:
    """
    Normalize user input to an arXiv id suitable for https://arxiv.org/src/{id}.
    Accepts plain ids, arxiv:ID, and abs/src URLs. Preserves version suffix if present.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    m = re.search(r"arxiv\.org/(?:abs|src)/([\w.-]+)", s, re.I)
    if m:
        return m.group(1)
    m = re.search(r"\barxiv:\s*([\w.-]+)", s, re.I)
    if m:
        return m.group(1)
    return s


def _safe_extract_tar_gz(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract tarball under dest; block path traversal. Use data filter when available."""
    dest = dest.resolve()
    extract_kw: dict[str, Any] = {}
    if sys.version_info >= (3, 12) or sys.version_info >= (3, 11, 4):
        extract_kw["filter"] = "data"
    for member in tar.getmembers():
        dest_path = (dest / member.name).resolve()
        try:
            dest_path.relative_to(dest)
        except ValueError:
            raise ValueError(f"Unsafe path in archive: {member.name!r}") from None
        tar.extract(member, dest, **extract_kw)


def _relative_file_list(root: Path, max_files: int = 300) -> tuple[list[str], bool]:
    """List files under root (POSIX-style paths), truncated to max_files."""
    out: list[str] = []
    truncated = False
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        out.append(p.relative_to(root).as_posix())
        if len(out) >= max_files:
            truncated = True
            break
    return out, truncated


async def _download_arxiv_source_and_extract(
    arxiv_id: str,
    output_dir: Optional[str],
    timeout: float = 120.0,
) -> dict[str, Any]:
    """
    Download LaTeX/source bundle from arXiv (tar.gz) and extract.
    """
    aid = _normalize_arxiv_source_id(arxiv_id)
    if not aid or not re.match(r"^[\w.-]+$", aid):
        raise ValueError(
            "Invalid arXiv id. Use e.g. 2503.23278, arXiv:2503.23278, or an arxiv.org abs/src URL."
        )

    base = output_dir or os.environ.get("SCHOLAR_ARXIV_SOURCE_DIR")
    if not base:
        base = str(Path(tempfile.gettempdir()) / "scholar-search-mcp-arxiv-src")
    root = Path(base).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    extract_root = root / aid.replace(os.sep, "_").replace("..", "_")
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)

    url = f"{ARXIV_SRC_BASE}/{aid}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        if response.status_code == 404:
            raise ValueError(
                f"No source package at {url} (404). The paper may have no submitted source."
            )
        response.raise_for_status()
        data = response.content

    if not data:
        raise ValueError("Empty response from arXiv source URL")

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            _safe_extract_tar_gz(tar, extract_root)
    except tarfile.TarError as e:
        raise ValueError(
            f"Download from arXiv was not a valid tar.gz archive: {e}. "
            f"If the paper only has PDF, source may be unavailable."
        ) from e

    files, truncated = _relative_file_list(extract_root)
    return {
        "arxiv_id": aid,
        "source_url": url,
        "extract_dir": str(extract_root),
        "files": files,
        "files_listed": len(files),
        "files_truncated": truncated,
    }


def _text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


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
        # CORE API GET /v3/search/works: q, scroll, offset, limit, stats only (no sort in docs)
        params: dict[str, Any] = {
            "q": query.strip(),
            "limit": min(limit, 100),
            "offset": start,
        }
        if year:
            try:
                if "-" in year:
                    y1, y2 = year.split("-")[:2]
                    y1, y2 = y1.strip()[:4], y2.strip()[:4]
                    params["q"] = f"{params['q']} yearPublished:[{y1} TO {y2}]"
                else:
                    y = year.strip()[:4]
                    params["q"] = f"{params['q']} yearPublished:{y}"
            except Exception:
                pass

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
        except Exception as e:
            logger.warning("CORE search request failed: %s", e)
            raise

        data = response.json()
        results = data.get("results") or []
        entries: list[dict[str, Any]] = []
        for r in results:
            paper = self._result_to_paper(r)
            if paper:
                entries.append(paper)
        if results and len(entries) < len(results):
            logger.debug(
                "CORE returned %s results, %s had valid url/title (some may lack doi/downloadUrl)",
                len(results),
                len(entries),
            )
        return {"total": data.get("total_hits", len(entries)), "entries": entries}

    def _result_to_paper(self, r: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Convert one CORE result to S2-compatible paper dict."""
        title = (r.get("title") or "").strip()
        if not title:
            return None

        url: Optional[str] = None
        if r.get("doi"):
            url = f"https://doi.org/{r['doi']}"
        if not url and r.get("downloadUrl"):
            du = r["downloadUrl"]
            if isinstance(du, str):
                url = du
            elif isinstance(du, dict):
                url = du.get("url") or du.get("link")
                if not url and isinstance(du.get("urls"), list) and du["urls"]:
                    url = du["urls"][0] if isinstance(du["urls"][0], str) else (du["urls"][0].get("url") or du["urls"][0].get("link") if isinstance(du["urls"][0], dict) else None)
        if not url and r.get("sourceFulltextUrls"):
            su = r["sourceFulltextUrls"]
            if isinstance(su, str):
                url = su
            elif isinstance(su, list) and su:
                url = su[0] if isinstance(su[0], str) else (su[0].get("url") or su[0].get("link") if isinstance(su[0], dict) else None)
            elif isinstance(su, dict):
                urls = su.get("urls") or su.get("url") or su.get("link")
                url = urls[0] if isinstance(urls, list) and urls else (urls if isinstance(urls, str) else None)
        if not url and r.get("id") is not None:
            url = f"https://core.ac.uk/works/{r['id']}"
        if not url:
            return None

        raw_date = r.get("publishedDate") or r.get("depositedDate")
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

        authors: list[dict[str, Any]] = []
        for a in r.get("authors") or []:
            name = a.get("name") if isinstance(a, dict) else (a if isinstance(a, str) else None)
            if name:
                authors.append({"name": name})

        pdf_url = r.get("downloadUrl")
        if isinstance(pdf_url, dict):
            pdf_url = pdf_url.get("url") if pdf_url else None
        if not pdf_url and r.get("sourceFulltextUrls"):
            su = r["sourceFulltextUrls"]
            pdf_url = su[0] if isinstance(su, list) and su else (su if isinstance(su, str) else None)

        return {
            "paperId": str(r.get("id", r.get("doi", ""))),
            "title": title,
            "abstract": (r.get("abstract") or r.get("fullText") or "")[:5000] or None,
            "year": year_val,
            "authors": authors,
            "citationCount": r.get("citationCount"),
            "referenceCount": None,
            "influentialCitationCount": None,
            "venue": (", ".join(j.get("title", "") for j in (r.get("journals") or []) if isinstance(j, dict) and j.get("title")) or None),
            "publicationTypes": r.get("documentType"),
            "publicationDate": date_str,
            "url": url,
            "pdfUrl": pdf_url,
            "source": "core",
        }


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
        # search_query: use 'all:' for full-text search (title, abstract, etc.)
        search_query = f"all:{query.strip()}"
        params: dict[str, Any] = {
            "search_query": search_query,
            "start": start,
            "max_results": min(limit, 2000),  # arXiv allows up to 2000 per request
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        if year:
            # submittedDate filter: [YYYYMMDDTTTT+TO+YYYYMMDDTTTT] in GMT
            try:
                if "-" in year:
                    y1, y2 = year.split("-")[:2]
                    y1, y2 = y1.strip()[:4], y2.strip()[:4]
                    params["search_query"] = f"{params['search_query']}+AND+submittedDate:[{y1}01010000+TO+{y2}12312359]"
                else:
                    y = year.strip()[:4]
                    params["search_query"] = f"{params['search_query']}+AND+submittedDate:[{y}01010000+TO+{y}12312359]"
            except Exception:
                pass

        url = f"{ARXIV_API_BASE}?search_query={quote_plus(params['search_query'])}&start={params['start']}&max_results={params['max_results']}&sortBy={params['sortBy']}&sortOrder={params['sortOrder']}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
        except Exception as e:
            logger.warning("arXiv search failed: %s", e)
            return {"totalResults": 0, "entries": []}

        root = ET.fromstring(response.text)
        total_el = root.find(f"{{{OPENSEARCH_NS}}}totalResults")
        total_results = int(_text(total_el)) if total_el is not None else 0

        entries: list[dict[str, Any]] = []
        for entry in root.findall(f"{{{ATOM_NS}}}entry"):
            # Skip error entries (arXiv returns errors as entry with summary containing "Error")
            summary_el = entry.find(f"{{{ATOM_NS}}}summary")
            if summary_el is not None and _text(entry.find(f"{{{ATOM_NS}}}title")).lower() == "error":
                continue
            paper = self._entry_to_paper(entry)
            if paper:
                entries.append(paper)
        return {"totalResults": total_results, "entries": entries}

    def _entry_to_paper(self, entry: ET.Element) -> Optional[dict[str, Any]]:
        """Convert one Atom entry to S2-compatible paper dict."""
        id_el = entry.find(f"{{{ATOM_NS}}}id")
        id_url = _text(id_el) if id_el is not None else ""
        arxiv_id = _arxiv_id_from_url(id_url)
        if not arxiv_id:
            return None

        title_el = entry.find(f"{{{ATOM_NS}}}title")
        title = _text(title_el).replace("\n", " ").strip()

        summary_el = entry.find(f"{{{ATOM_NS}}}summary")
        abstract = _text(summary_el).replace("\n", " ").strip() if summary_el is not None else ""

        published_el = entry.find(f"{{{ATOM_NS}}}published")
        updated_el = entry.find(f"{{{ATOM_NS}}}updated")
        date_str = _text(published_el) or _text(updated_el)
        year_val: Optional[int] = None
        if date_str and len(date_str) >= 4:
            try:
                year_val = int(date_str[:4])
            except ValueError:
                pass

        authors: list[dict[str, Any]] = []
        for author in entry.findall(f"{{{ATOM_NS}}}author"):
            name_el = author.find(f"{{{ATOM_NS}}}name")
            name = _text(name_el) if name_el is not None else ""
            if name:
                authors.append({"name": name})

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

        return {
            "paperId": arxiv_id,
            "title": title,
            "abstract": abstract or None,
            "year": year_val,
            "authors": authors,
            "citationCount": None,
            "referenceCount": None,
            "influentialCitationCount": None,
            "venue": venue,
            "publicationTypes": None,
            "publicationDate": date_str or None,
            "url": link_alternate or f"https://arxiv.org/abs/{arxiv_id}",
            "pdfUrl": link_pdf,
            "source": "arxiv",
        }


class SemanticScholarClient:
    """Semantic Scholar API client."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.headers = {}
        if api_key:
            self.headers["x-api-key"] = api_key

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        max_retries: int = 4,
        base_delay: float = 1.0,
    ) -> dict[str, Any]:
        """Send HTTP request with exponential backoff on 429."""
        url = f"{API_BASE_URL}/{endpoint}"
        # 429 时需更多重试次数，取较大值
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
                    # 429 时多重试几次再退避（使用 MAX_429_RETRIES，退避时间指数增长）
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
        return await self._request("GET", "paper/search", params=params)

    async def get_paper_details(
        self,
        paper_id: str,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get paper details."""
        params = {"fields": ",".join(fields or DEFAULT_PAPER_FIELDS)}
        return await self._request("GET", f"paper/{paper_id}", params=params)

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
        return await self._request(
            "GET", f"paper/{paper_id}/citations", params=params
        )

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
        return await self._request(
            "GET", f"paper/{paper_id}/references", params=params
        )

    async def get_author_info(
        self,
        author_id: str,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Get author info."""
        params = {"fields": ",".join(fields or DEFAULT_AUTHOR_FIELDS)}
        return await self._request("GET", f"author/{author_id}", params=params)

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
        return await self._request(
            "GET", f"author/{author_id}/papers", params=params
        )

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
        return await self._request(
            "GET",
            f"recommendations/v1/papers/forpaper/{paper_id}",
            params=params,
        )

    async def batch_get_papers(
        self,
        paper_ids: list[str],
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Batch get papers (up to 500)."""
        json_data = {"ids": paper_ids[:500]}
        params = {"fields": ",".join(fields or DEFAULT_PAPER_FIELDS)}
        return await self._request(
            "POST", "paper/batch", params=params, json_data=json_data
        )


def _env_bool(key: str, default: bool = True) -> bool:
    """Parse env as bool: 1/true/yes (case-insensitive) => True; 0/false/no => False."""
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes")


app = Server("scholar-search")
api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
core_api_key = os.environ.get("CORE_API_KEY")
enable_core = _env_bool("SCHOLAR_SEARCH_ENABLE_CORE", True)
enable_semantic_scholar = _env_bool("SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR", True)
enable_arxiv = _env_bool("SCHOLAR_SEARCH_ENABLE_ARXIV", True)
client = SemanticScholarClient(api_key=api_key)
core_client = CoreApiClient(api_key=core_api_key)
arxiv_client = ArxivClient()


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="search_papers",
            description="Search academic papers by keyword. Optional filters: year, venue.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {
                        "type": "number",
                        "description": "Max results (default 10, max 100)",
                        "default": 10,
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return",
                    },
                    "year": {
                        "type": "string",
                        "description": "Year filter, e.g. '2020-2023' or '2023'",
                    },
                    "venue": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Venue names to filter",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_paper_details",
            description="Get paper details. Supports DOI, ArXiv ID, Semantic Scholar ID, or URL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {
                        "type": "string",
                        "description": "Paper ID (DOI, ArXiv ID, S2 ID, etc.)",
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return",
                    },
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="get_paper_citations",
            description="Get list of papers that cite this paper.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string", "description": "Paper ID"},
                    "limit": {
                        "type": "number",
                        "description": "Max results (default 100, max 1000)",
                        "default": 100,
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return",
                    },
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="get_paper_references",
            description="Get list of references of this paper.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string", "description": "Paper ID"},
                    "limit": {
                        "type": "number",
                        "description": "Max results (default 100, max 1000)",
                        "default": 100,
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return",
                    },
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="get_author_info",
            description="Get author details.",
            inputSchema={
                "type": "object",
                "properties": {
                    "author_id": {"type": "string", "description": "Author ID"},
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return",
                    },
                },
                "required": ["author_id"],
            },
        ),
        Tool(
            name="get_author_papers",
            description="Get papers by author.",
            inputSchema={
                "type": "object",
                "properties": {
                    "author_id": {"type": "string", "description": "Author ID"},
                    "limit": {
                        "type": "number",
                        "description": "Max results (default 100, max 1000)",
                        "default": 100,
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return",
                    },
                },
                "required": ["author_id"],
            },
        ),
        Tool(
            name="get_paper_recommendations",
            description="Get similar paper recommendations for a paper.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string", "description": "Paper ID"},
                    "limit": {
                        "type": "number",
                        "description": "Max results (default 10, max 100)",
                        "default": 10,
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return",
                    },
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="batch_get_papers",
            description="Get details for multiple papers (up to 500).",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of paper IDs",
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return",
                    },
                },
                "required": ["paper_ids"],
            },
        ),
        Tool(
            name="download_arxiv_source",
            description=(
                "Download arXiv LaTeX/source bundle (tar.gz from https://arxiv.org/src/{id}) "
                "and extract it to a directory. Default base directory is SCHOLAR_ARXIV_SOURCE_DIR "
                "or the system temp folder. Overwrites a previous extract of the same id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "arxiv_id": {
                        "type": "string",
                        "description": (
                            "arXiv paper id, e.g. 2503.23278 or 2503.23278v1; or arXiv/abs/src URL; "
                            "or arxiv:2503.23278"
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Optional directory under which to create a folder named after the id. "
                            "If omitted, uses env SCHOLAR_ARXIV_SOURCE_DIR or temp/scholar-search-mcp-arxiv-src"
                        ),
                    },
                },
                "required": ["arxiv_id"],
            },
        ),
    ]


def _merge_search_results(
    s2_response: dict[str, Any],
    arxiv_response: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    """Merge Semantic Scholar and arXiv results; keep same response shape (total, offset, data)."""
    s2_data = list(s2_response.get("data") or [])
    arxiv_entries = list(arxiv_response.get("entries") or [])
    for p in s2_data:
        p.setdefault("source", "semantic_scholar")
    # Dedupe: skip arXiv entries whose id already appears in S2 (when externalIds present)
    seen_arxiv_ids = set()
    for p in s2_data:
        eid = p.get("externalIds") or {}
        arxiv_id = eid.get("ArXiv")
        if arxiv_id:
            seen_arxiv_ids.add(str(arxiv_id))
    merged = list(s2_data)
    for p in arxiv_entries:
        aid = p.get("paperId") or ""
        if aid and aid not in seen_arxiv_ids:
            seen_arxiv_ids.add(aid)
            merged.append(p)
    merged = merged[:limit]
    return {
        "total": len(merged),
        "offset": s2_response.get("offset", 0),
        "data": merged,
    }


def _core_response_to_merged(core_response: dict[str, Any], limit: int) -> dict[str, Any]:
    """Convert CORE search response to unified shape (total, offset, data)."""
    entries = list(core_response.get("entries") or [])
    return {
        "total": core_response.get("total", len(entries)),
        "offset": 0,
        "data": entries[:limit],
    }


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    if name == "search_papers":
        limit = arguments.get("limit", 10)
        limit = min(max(1, limit), 100)
        year = arguments.get("year")
        query = arguments["query"]
        # Fallback chain: CORE → Semantic Scholar → arXiv (each step only if channel enabled)
        result = None
        if enable_core:
            try:
                core_response = await core_client.search(
                    query=query,
                    limit=limit,
                    start=0,
                    year=year,
                )
                if core_response.get("entries"):
                    result = _core_response_to_merged(core_response, limit)
                    logger.info("search_papers: using CORE API results")
            except Exception as e:
                logger.info("search_papers: CORE failed (%s), falling back to next channel", e)
        if result is None and enable_semantic_scholar:
            try:
                s2_response = await client.search_papers(
                    query=query,
                    limit=limit,
                    fields=arguments.get("fields"),
                    year=year,
                    venue=arguments.get("venue"),
                )
                if s2_response.get("data"):
                    result = {
                        "total": s2_response.get("total", len(s2_response.get("data", []))),
                        "offset": s2_response.get("offset", 0),
                        "data": (s2_response.get("data") or [])[:limit],
                    }
                    for p in result["data"]:
                        p.setdefault("source", "semantic_scholar")
                    logger.info("search_papers: using Semantic Scholar results")
            except Exception as e:
                logger.info("search_papers: Semantic Scholar failed (%s), falling back to next channel", e)
        if result is None and enable_arxiv:
            arxiv_response = await arxiv_client.search(
                query=query,
                limit=limit,
                year=year,
            )
            if arxiv_response.get("entries"):
                result = _core_response_to_merged(
                    {"total": arxiv_response.get("totalResults", 0), "entries": arxiv_response["entries"]},
                    limit,
                )
                logger.info("search_papers: using arXiv results")
        if result is None:
            result = {"total": 0, "offset": 0, "data": []}
    elif name == "get_paper_details":
        result = await client.get_paper_details(
            paper_id=arguments["paper_id"],
            fields=arguments.get("fields"),
        )
    elif name == "get_paper_citations":
        result = await client.get_paper_citations(
            paper_id=arguments["paper_id"],
            limit=arguments.get("limit", 100),
            fields=arguments.get("fields"),
        )
    elif name == "get_paper_references":
        result = await client.get_paper_references(
            paper_id=arguments["paper_id"],
            limit=arguments.get("limit", 100),
            fields=arguments.get("fields"),
        )
    elif name == "get_author_info":
        result = await client.get_author_info(
            author_id=arguments["author_id"],
            fields=arguments.get("fields"),
        )
    elif name == "get_author_papers":
        result = await client.get_author_papers(
            author_id=arguments["author_id"],
            limit=arguments.get("limit", 100),
            fields=arguments.get("fields"),
        )
    elif name == "get_paper_recommendations":
        result = await client.get_recommendations(
            paper_id=arguments["paper_id"],
            limit=arguments.get("limit", 10),
            fields=arguments.get("fields"),
        )
    elif name == "batch_get_papers":
        result = await client.batch_get_papers(
            paper_ids=arguments["paper_ids"],
            fields=arguments.get("fields"),
        )
    elif name == "download_arxiv_source":
        result = await _download_arxiv_source_and_extract(
            arxiv_id=arguments["arxiv_id"],
            output_dir=arguments.get("output_dir"),
        )
    else:
        raise ValueError(f"Unknown tool: {name}")

    return [
        TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )
    ]


def main() -> None:
    """Run the MCP server."""
    import anyio
    from mcp.server.stdio import stdio_server

    logger.info("Starting Scholar Search MCP Server...")
    logger.info("Search channels: CORE=%s, Semantic Scholar=%s, arXiv=%s", enable_core, enable_semantic_scholar, enable_arxiv)
    if api_key:
        logger.info("Semantic Scholar API key detected")
    else:
        logger.warning("No Semantic Scholar API key; using public rate limits")
    if core_api_key:
        logger.info("CORE API key set (search tries CORE first with higher limits)")
    else:
        logger.info("No CORE API key; search still tries CORE first (subject to rate limits), then S2/arXiv")

    async def arun() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )

    anyio.run(arun)


if __name__ == "__main__":
    main()
