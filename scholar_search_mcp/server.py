"""Scholar Search MCP Server - Semantic Scholar API via Model Context Protocol."""

import asyncio
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

from typing import Any, Optional

import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scholar-search-mcp")

API_BASE_URL = "https://api.semanticscholar.org/graph/v1"
ARXIV_API_BASE = "https://export.arxiv.org/api/query"

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


def _text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


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

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(max_retries + 1):
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=json_data,
                )

                if response.status_code == 429:
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        retry_after = response.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            delay = max(delay, float(retry_after))
                        logger.warning(
                            "Rate limited (429), retrying in %.1fs (%s/%s)",
                            delay,
                            attempt + 1,
                            max_retries,
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


app = Server("scholar-search")
api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
client = SemanticScholarClient(api_key=api_key)
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


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    if name == "search_papers":
        limit = arguments.get("limit", 10)
        limit = min(max(1, limit), 100)
        year = arguments.get("year")
        # Query both sources in parallel; venue filter only applies to S2
        s2_task = client.search_papers(
            query=arguments["query"],
            limit=limit,
            fields=arguments.get("fields"),
            year=year,
            venue=arguments.get("venue"),
        )
        arxiv_task = arxiv_client.search(
            query=arguments["query"],
            limit=limit,
            year=year,
        )
        s2_response, arxiv_response = await asyncio.gather(s2_task, arxiv_task)
        result = _merge_search_results(s2_response, arxiv_response, limit)
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
    if api_key:
        logger.info("API key detected")
    else:
        logger.warning("No API key; using public rate limits")

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
