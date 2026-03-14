# Semantic Scholar API Guide

This guide describes how to use the Semantic Scholar Graph API respectfully and effectively when you have an approved API key with a strict rate limit of `1 request per second`, cumulative across all endpoints.

It assumes:

- Python async code built around `httpx`
- retries handled with `tenacity`
- concurrency bounded with `asyncio.Semaphore`
- client-side pacing that stays below the published limit
- API keys loaded from environment variables, with a `.env` file during local development

## Operating Principles

If you remember only a few things, make them these:

1. Treat `1 request per second` as a hard ceiling, not a target.
2. Use one shared rate limiter across every Semantic Scholar endpoint.
3. Keep requests small by asking only for the fields you need.
4. Prefer batch endpoints and caching over repeated single-record fetches.
5. Retry sparingly, honor `Retry-After`, and never retry in a tight loop.

The most common failure mode is assuming async concurrency is harmless. It is not. Ten coroutines can still stampede a service unless they share the same limiter.

## Authentication

Semantic Scholar expects the API key in the `x-api-key` header.

References:

- Tutorial: https://www.semanticscholar.org/product/api/tutorial
- OpenAPI schema: https://api.semanticscholar.org/graph/v1/swagger.json

Example header:

```http
x-api-key: YOUR_API_KEY
```

## API Surface Overview

Semantic Scholar exposes multiple APIs with different base URLs:

- Academic Graph API: `https://api.semanticscholar.org/graph/v1`
- Recommendations API: `https://api.semanticscholar.org/recommendations/v1`
- Datasets API: `https://api.semanticscholar.org/datasets/v1`

If your application is interactive and needs paper, author, citation, or reference metadata, most traffic will go to the Academic Graph API. If you need paper recommendations, use the Recommendations API. If you need corpus-scale access beyond what `1 request/second` can support, switch to the Datasets API instead of trying to squeeze large crawls through the live endpoints.

## Core Endpoint Map

The endpoints below are the ones most applications actually need.

### Paper Data

| Endpoint | Method | Purpose | Pagination | Notes |
| --- | --- | --- | --- | --- |
| `/paper/search` | `GET` | Relevance-ranked paper search | `offset`, `limit` | Supports up to 100 results per call and up to 1,000 ranked results total. No special query syntax. |
| `/paper/search/bulk` | `GET` | Bulk paper search for large retrieval jobs | `token` | Supports query syntax, sorting, and up to 1,000 papers per call. Preferred for larger retrieval. |
| `/paper/search/match` | `GET` | Best title match for a query | none | Returns the single closest paper title match. |
| `/paper/autocomplete` | `GET` | Query completion for paper titles | none | Designed for typeahead or interactive search UI. |
| `/paper/{paper_id}` | `GET` | One paper by ID | none | Supports many ID formats. |
| `/paper/batch` | `POST` | Fetch multiple papers at once | none | Up to 500 paper IDs per call. Strongly preferred over N single-paper requests. |
| `/paper/{paper_id}/authors` | `GET` | Authors of a paper | `offset`, `limit` | Author detail fields are controlled via `fields`. |
| `/paper/{paper_id}/citations` | `GET` | Papers citing this paper | `offset`, `limit` | Citation objects include `citingPaper` plus metadata like `contexts` and `isInfluential`. |
| `/paper/{paper_id}/references` | `GET` | Papers referenced by this paper | `offset`, `limit` | Reference objects include `citedPaper` plus metadata like `contexts` and `isInfluential`. |

### Author Data

| Endpoint | Method | Purpose | Pagination | Notes |
| --- | --- | --- | --- | --- |
| `/author/search` | `GET` | Search for authors by name | `offset`, `limit` | Plain-text only. Hyphenated query terms can fail to match well. |
| `/author/{author_id}` | `GET` | One author by ID | none | Returns minimal fields by default. |
| `/author/{author_id}/papers` | `GET` | Papers by an author | `offset`, `limit` | Can filter with `publicationDateOrYear`. |
| `/author/batch` | `POST` | Fetch multiple authors at once | none | Up to 1,000 author IDs per call and 10 MB response cap. |

### Snippet Text

| Endpoint | Method | Purpose | Pagination | Notes |
| --- | --- | --- | --- | --- |
| `/snippet/search` | `GET` | Search for matching text snippets | `limit` only | Returns snippet text plus paper info and score. Useful for quote-like retrieval, not for standard metadata lookup. |

### Recommendations API

| Endpoint | Method | Purpose | Notes |
| --- | --- | --- | --- |
| `/recommendations/v1/papers/forpaper/{paper_id}` | `GET` | Recommendations from one seed paper | Good for interactive “more like this” flows. |
| `/recommendations/v1/papers` | `POST` | Recommendations from positive and negative seed sets | More flexible and usually better for guided retrieval. |

### Datasets API

| Endpoint | Method | Purpose | Notes |
| --- | --- | --- | --- |
| `/datasets/v1/release` | `GET` | List available releases | Use when you want the release catalog. |
| `/datasets/v1/release/{release_id}` | `GET` | List datasets for a release | `latest` is supported as a release selector. |
| `/datasets/v1/release/{release_id}/dataset/{dataset_name}` | `GET` | Get dataset download links | Requires API key. |
| `/datasets/v1/diffs/{start}/to/{end}/{dataset}` | `GET` | Incremental updates between releases | Requires API key. |

## Supported Paper ID Formats

The paper lookup family accepts more than one identifier format. For `/paper/{paper_id}` and related paper subresources, the documentation lists support for:

- raw Semantic Scholar `paperId` hash, for example `649def34f8be52c8b66281af98ae884c09aef38b`
- `CorpusId:<id>`
- `DOI:<doi>`
- `ARXIV:<id>`
- `MAG:<id>`
- `ACL:<id>`
- `PMID:<id>`
- `PMCID:<id>`
- `URL:<url>` for supported domains such as Semantic Scholar, arXiv, ACL, ACM, and bioRxiv

Examples:

```text
649def34f8be52c8b66281af98ae884c09aef38b
CorpusId:215416146
DOI:10.18653/v1/N18-3011
ARXIV:2106.15928
URL:https://arxiv.org/abs/2106.15928v1
```

This matters because batch endpoints can often mix ID formats, which is useful when your upstream sources are inconsistent.

## Default Response Behavior and `fields`

Most Academic Graph endpoints support a `fields` query parameter. This is one of the most important controls in the API.

General rules:

- `fields` is a single comma-separated string, not a repeated multi-value parameter.
- If `fields` is omitted, endpoints return a small default shape.
- `paperId` is always returned for paper resources.
- `authorId` is always returned for author resources.
- nested fields use dot notation

Examples:

```text
fields=title,url,year
fields=title,authors
fields=title,authors.name,authors.authorId
fields=contexts,isInfluential,citingPaper.title,citingPaper.year
fields=title,embedding.specter_v2
fields=name,url,papers.title,papers.year
```

In practice, the most important field groups are:

- core paper metadata: `title`, `abstract`, `year`, `venue`, `publicationDate`, `url`
- access and identifiers: `externalIds`, `isOpenAccess`, `openAccessPdf`, `citationStyles`
- impact: `citationCount`, `referenceCount`, `influentialCitationCount`
- classification: `fieldsOfStudy`, `s2FieldsOfStudy`, `publicationTypes`
- relations: `authors`, `citations`, `references`
- advanced extras: `embedding`, `tldr`, `textAvailability`

For authors, commonly requested fields are:

- `name`
- `url`
- `affiliations`
- `homepage`
- `paperCount`
- `citationCount`
- `hIndex`
- `papers`

Nested defaults matter:

- requesting `authors` returns default author subfields like `authorId` and `name`
- requesting `citations` or `references` returns default paper subfields like `paperId` and `title`
- you only need dot notation when you want more than those defaults

## Common Query Parameters

The parameters below appear across the paper search and listing endpoints.

| Parameter | Type | Meaning | Common Endpoints |
| --- | --- | --- | --- |
| `query` | string | Search text | `/paper/search`, `/paper/search/bulk`, `/paper/search/match`, `/author/search`, `/snippet/search` |
| `fields` | string | Comma-separated response mask | Most graph endpoints |
| `offset` | integer | Offset-based pagination start | `/paper/search`, `/author/search`, citations, references, author papers |
| `limit` | integer | Maximum results in one response | Most list endpoints |
| `token` | string | Cursor for bulk search pagination | `/paper/search/bulk` |
| `year` | string | Publication year or range | paper search endpoints, snippet search |
| `publicationDateOrYear` | string | Date or date-range filter | paper search, author papers, citations, references, snippet search |
| `venue` | string | Comma-separated venue filter | paper search endpoints, snippet search |
| `fieldsOfStudy` | string | Comma-separated field-of-study filter | paper search endpoints, snippet search |
| `publicationTypes` | string | Comma-separated publication type filter | paper search endpoints |
| `openAccessPdf` | flag-like query param | Only return papers with public PDFs | paper search endpoints |
| `minCitationCount` | integer-like string | Minimum citations filter | paper search endpoints, snippet search |
| `sort` | string | Sort order for bulk search | `/paper/search/bulk` |

### `query`

There are two important query modes:

- `/paper/search` and `/author/search` use plain text only. No advanced boolean syntax.
- `/paper/search/bulk` supports boolean and fuzzy syntax.

Bulk search syntax supported by the tutorial and schema includes:

- `+` for AND
- `|` for OR
- `-` to negate a term
- quotes for phrases
- `*` for prefix matching
- parentheses for precedence
- `~N` for edit distance or phrase slop

Examples:

```text
"generative ai"
((cloud computing) | virtualization) +security -privacy
fish*
bugs~3
"blue lake"~3
```

### `year`

The `year` parameter accepts exact and ranged forms:

```text
2019
2016-2020
2010-
-2015
2023-
```

### `publicationDateOrYear`

This parameter is more expressive than `year` and accepts dates or date prefixes:

```text
2019-03-05
2019-03
2019
2016-03-05:2020-06-06
1981-08-25:
:2015-01
2015:2020
```

If a specific publication date is not known, the documentation says the API may treat the paper as if it were published on January 1 of the publication year for filtering purposes.

### `publicationTypes`

The Graph API documentation lists these supported publication types for paper search filtering:

- `Review`
- `JournalArticle`
- `CaseReport`
- `ClinicalTrial`
- `Conference`
- `Dataset`
- `Editorial`
- `LettersAndComments`
- `MetaAnalysis`
- `News`
- `Study`
- `Book`
- `BookSection`

Use comma-separated values for OR behavior:

```text
publicationTypes=Review,JournalArticle
```

### `fieldsOfStudy`

The documented high-level categories include:

- `Computer Science`
- `Medicine`
- `Chemistry`
- `Biology`
- `Materials Science`
- `Physics`
- `Geology`
- `Psychology`
- `Art`
- `History`
- `Geography`
- `Sociology`
- `Business`
- `Political Science`
- `Economics`
- `Philosophy`
- `Mathematics`
- `Engineering`
- `Environmental Science`
- `Agricultural and Food Sciences`
- `Education`
- `Law`
- `Linguistics`

### `openAccessPdf`

This behaves like a presence filter. The schema describes it as a parameter that does not accept a value. In practice, many clients send it as a bare query parameter.

## Pagination Models

Semantic Scholar uses two different pagination patterns.

### Offset Pagination

Used by endpoints such as:

- `/paper/search`
- `/author/search`
- `/author/{author_id}/papers`
- `/paper/{paper_id}/citations`
- `/paper/{paper_id}/references`
- `/paper/{paper_id}/authors`

Typical response shape:

```json
{
    "total": 12345,
    "offset": 0,
    "next": 100,
    "data": []
}
```

### Token Pagination

Used by `/paper/search/bulk`.

Typical response shape:

```json
{
    "total": 12345,
    "token": "next-page-token",
    "data": []
}
```

The client should repeat the same request with the returned `token` until the token disappears.

Important difference:

- relevance search uses `offset` and `limit`
- bulk search uses continuation `token`

Do not try to mix those pagination models.

## Important Endpoint Limits

These limits are operationally important when designing your client:

- `/paper/search`: `limit <= 100`
- `/paper/search`: only up to 1,000 relevance-ranked results are available
- `/paper/search/bulk`: up to 1,000 papers per call and up to 10,000,000 papers retrievable across pagination
- `/paper/batch`: up to 500 paper IDs per call
- `/author/batch`: up to 1,000 author IDs per call
- many graph responses have a `10 MB` response-size limit
- `/paper/batch` docs also note caps around nested citation volume in one response

The `10 MB` limit is especially relevant if you request deep nested fields like `citations`, `references`, or `papers` together with large page sizes.

## Response Shapes You Will Actually See

### Paper search

`/paper/search` returns a batch object with:

- `total`: approximate total matches
- `offset`
- `next`
- `data`: array of paper objects

The docs explicitly say `total` is approximate and should not be treated as an exact corpus count for keyword presence.

### Bulk paper search

`/paper/search/bulk` returns:

- `total`: approximate total matches
- `token`: continuation token when more data exists
- `data`: array of paper objects

### Single paper

`/paper/{paper_id}` returns one paper object. Common fields include:

- `paperId`
- `corpusId`
- `externalIds`
- `url`
- `title`
- `abstract`
- `venue`
- `publicationVenue`
- `year`
- `referenceCount`
- `citationCount`
- `influentialCitationCount`
- `isOpenAccess`
- `openAccessPdf`
- `fieldsOfStudy`
- `s2FieldsOfStudy`
- `publicationTypes`
- `publicationDate`
- `journal`
- `citationStyles`
- `authors`
- `citations`
- `references`
- `embedding`
- `tldr`
- `textAvailability`

### Citations and references

`/paper/{paper_id}/citations` returns citation objects with fields such as:

- `contexts`
- `intents`
- `contextsWithIntent`
- `isInfluential`
- `citingPaper`

`/paper/{paper_id}/references` returns reference objects with the same surrounding metadata, but the nested paper field is `citedPaper` instead of `citingPaper`.

### Author objects

Common author fields include:

- `authorId`
- `externalIds`
- `url`
- `name`
- `affiliations`
- `homepage`
- `paperCount`
- `citationCount`
- `hIndex`
- `papers`

### Snippet search

`/snippet/search` returns ranked snippet matches. Each result contains:

- `snippet`
- `score`
- `paper`

The `snippet` object can include `text`, `snippetKind`, `section`, `snippetOffset`, and annotation data such as sentence spans and reference mentions.

## Status Codes and Failure Modes

The tutorial calls out these common statuses:

- `200 OK`
- `400 Bad Request`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `429 Too Many Requests`
- `500 Internal Server Error`

The schema gives more concrete examples of `400` failures:

- unsupported field masks
- unacceptable query params
- response would exceed maximum size

That last one is important. Large nested field requests can fail even when the endpoint and IDs are valid.

## When To Use Which Search Endpoint

Use `/paper/search` when:

- you want Semantic Scholar's relevance ranking
- you only need the top results
- you are building an interactive search UI

Use `/paper/search/bulk` when:

- you need more than 1,000 results
- you want sort support
- you need advanced query syntax
- you are doing batch ingestion or offline enrichment

Use `/paper/search/match` when:

- you have an approximate title and want the single closest record

Use `/paper/autocomplete` when:

- you are implementing typeahead or suggestion UX

## Recommendations API Details

The tutorial highlights two recommendation patterns:

- single seed paper recommendations
- recommendations from lists of positive and negative seed papers

The multi-seed endpoint is a `POST` to `https://api.semanticscholar.org/recommendations/v1/papers` and accepts a JSON body containing:

```json
{
    "positivePaperIds": ["paper-id-1", "paper-id-2"],
    "negativePaperIds": ["paper-id-3"]
}
```

Typical query parameters include:

- `fields`
- `limit`

This endpoint is useful when you want to steer recommendations away from known-bad directions by using negative seeds.

## Datasets API Details

The tutorial is clear on the intended escalation path:

- use live APIs for interactive and moderate workloads
- use datasets when you need high-volume or corpus-scale access

Typical datasets workflow:

1. list releases
2. inspect datasets in a release
3. request download links for a dataset
4. optionally apply diffs between releases instead of re-downloading everything

This is the right approach when `1 request/second` is structurally too low for the job you are trying to do.

## Practical Examples

### Relevance search

```http
GET /graph/v1/paper/search?query=generative%20ai&limit=10&fields=title,year,authors,url
x-api-key: YOUR_API_KEY
```

### Bulk search with filters

```http
GET /graph/v1/paper/search/bulk?query=%22generative%20ai%22&fields=title,url,publicationTypes,publicationDate,openAccessPdf&year=2023-
x-api-key: YOUR_API_KEY
```

### Single paper by DOI

```http
GET /graph/v1/paper/DOI:10.18653/v1/N18-3011?fields=title,abstract,year,citationCount
x-api-key: YOUR_API_KEY
```

### Batch paper lookup

```http
POST /graph/v1/paper/batch?fields=title,year,citationCount
x-api-key: YOUR_API_KEY
Content-Type: application/json

{
    "ids": [
        "649def34f8be52c8b66281af98ae884c09aef38b",
        "ARXIV:2106.15928"
    ]
}
```

### Author batch lookup

```http
POST /graph/v1/author/batch?fields=name,url,paperCount,hIndex
x-api-key: YOUR_API_KEY
Content-Type: application/json

{
    "ids": ["1741101", "1780531"]
}
```

### Recommendations with positive and negative seeds

```http
POST /recommendations/v1/papers?fields=title,url,citationCount,authors&limit=100
x-api-key: YOUR_API_KEY
Content-Type: application/json

{
    "positivePaperIds": ["02138d6d094d1e7511c157f0b1a3dd4e5b20ebee"],
    "negativePaperIds": ["0045ad0c1e14a4d1f4b011c92eb36b8df63d65bc"]
}
```

## Design Guidance From the API Shape

The API design itself suggests some implementation choices:

- use `/paper/batch` instead of repeated `/paper/{paper_id}` calls
- use `/author/batch` instead of repeated `/author/{author_id}` calls
- use `/paper/search/bulk` instead of paginating deep into `/paper/search`
- keep `fields` narrow to avoid both latency and `10 MB` response errors
- treat recommendations and datasets as separate workloads with separate client helpers

That makes your code both faster and more respectful to the service.

## Environment Variables and `.env`

Use environment variables everywhere. During local development, load them from a `.env` file. In CI or production, inject them from your runtime environment or secret manager instead.

Example `.env`:

```dotenv
SEMANTIC_SCHOLAR_API_KEY=replace-with-real-key
SEMANTIC_SCHOLAR_BASE_URL=https://api.semanticscholar.org/graph/v1
SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS=1.25
SEMANTIC_SCHOLAR_MAX_CONCURRENCY=2
SEMANTIC_SCHOLAR_TIMEOUT_SECONDS=30
```

Why `1.25` seconds instead of exactly `1.0`?

- clock drift happens
- event loops are not perfectly precise
- multiple tasks can wake up at nearly the same time
- staying a bit under the ceiling is better than discovering the real limit through `429` responses

Example settings loader:

```python
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class SemanticScholarSettings:
    api_key: str
    base_url: str = os.getenv(
        "SEMANTIC_SCHOLAR_BASE_URL",
        "https://api.semanticscholar.org/graph/v1",
    )
    min_interval_seconds: float = float(
        os.getenv("SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS", "1.25")
    )
    max_concurrency: int = int(
        os.getenv("SEMANTIC_SCHOLAR_MAX_CONCURRENCY", "2")
    )
    timeout_seconds: float = float(
        os.getenv("SEMANTIC_SCHOLAR_TIMEOUT_SECONDS", "30")
    )

    @classmethod
    def from_env(cls) -> "SemanticScholarSettings":
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("SEMANTIC_SCHOLAR_API_KEY is not set")
        return cls(api_key=api_key)
```

Do not commit `.env` files. Keep `.env.example` in the repo if you want a template, but never commit real credentials.

## Respectful Async Client Design

Good behavior requires three separate controls:

1. A shared rate limiter for throughput.
2. A semaphore for bounded in-flight work.
3. Retries for transient failures.

These solve different problems.

- The rate limiter keeps you below the service quota.
- The semaphore prevents internal task explosions and connection churn.
- Retries absorb temporary failures such as `429`, `502`, `503`, and `504`.

If you use only retries, you are reacting after overload instead of preventing it.

## Reference Implementation

This example uses a monotonic-clock limiter that guarantees a minimum delay between request starts across all tasks.

```python
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


load_dotenv()

API_KEY = os.environ["SEMANTIC_SCHOLAR_API_KEY"]
BASE_URL = os.getenv(
    "SEMANTIC_SCHOLAR_BASE_URL",
    "https://api.semanticscholar.org/graph/v1",
)
MIN_INTERVAL_SECONDS = float(
    os.getenv("SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS", "1.25")
)
MAX_CONCURRENCY = int(os.getenv("SEMANTIC_SCHOLAR_MAX_CONCURRENCY", "2"))
TIMEOUT_SECONDS = float(os.getenv("SEMANTIC_SCHOLAR_TIMEOUT_SECONDS", "30"))


class SemanticScholarRateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval_seconds = min_interval_seconds
        self._lock = asyncio.Lock()
        self._next_allowed_time = 0.0

    async def wait_for_turn(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next_allowed_time:
                await asyncio.sleep(self._next_allowed_time - now)
            self._next_allowed_time = time.monotonic() + self._min_interval_seconds


class SemanticScholarRetryableError(Exception):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Retryable response: {response.status_code}")


def _before_sleep(retry_state: RetryCallState) -> None:
    exception = retry_state.outcome.exception()
    if isinstance(exception, SemanticScholarRetryableError):
        retry_after = exception.response.headers.get("Retry-After")
        if retry_after:
            print(
                "retrying after status",
                exception.response.status_code,
                "retry-after=",
                retry_after,
            )


class SemanticScholarClient:
    def __init__(self) -> None:
        self._headers = {
            "x-api-key": API_KEY,
            "Accept": "application/json",
            "User-Agent": "scholar-search-mcp/0.1",
        }
        self._limiter = SemanticScholarRateLimiter(
            min_interval_seconds=MIN_INTERVAL_SECONDS
        )
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=self._headers,
            timeout=TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=MAX_CONCURRENCY),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(
                (httpx.TimeoutException, httpx.NetworkError, SemanticScholarRetryableError)
            ),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            stop=stop_after_attempt(5),
            reraise=True,
            before_sleep=_before_sleep,
        ):
            with attempt:
                async with self._semaphore:
                    await self._limiter.wait_for_turn()
                    response = await self._client.request(
                        method,
                        path,
                        params=params,
                        json=json_data,
                    )

                if response.status_code in {429, 502, 503, 504}:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        await asyncio.sleep(float(retry_after))
                    raise SemanticScholarRetryableError(response)

                response.raise_for_status()
                return response.json()

        raise RuntimeError("request retry loop exited unexpectedly")

    async def search_papers(
        self,
        query: str,
        *,
        limit: int = 10,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        effective_fields = fields or [
            "paperId",
            "title",
            "year",
            "authors",
            "abstract",
            "url",
        ]
        return await self._request(
            "GET",
            "/paper/search",
            params={
                "query": query,
                "limit": min(limit, 100),
                "fields": ",".join(effective_fields),
            },
        )
```

## Why This Pattern Works

The important detail is that the limiter is shared by the whole client. Every endpoint goes through it.

That means all of these share the same budget:

- paper search
- paper detail lookup
- author lookup
- citations
- references
- recommendations
- batch operations

That is exactly what you want when the provider says the limit is cumulative across all endpoints.

## Choosing Good Defaults

Use conservative defaults unless you have measured reason not to.

Recommended starting point:

- request spacing: `1.25s`
- max concurrency: `2`
- timeout: `30s`
- retry attempts: `5`
- retryable statuses: `429`, `502`, `503`, `504`

Why a semaphore of `2` if rate is only `1 rps`?

- it still bounds queued work and connection count
- it prevents accidental fan-out if many tasks call the client at once
- it allows one request to be in progress while other tasks remain structured around the same client

If you want the strictest possible behavior, set concurrency to `1`. That is completely reasonable for this API budget.

## Field Selection

Do not request large field sets by default. Ask only for fields you need for the current action.

Good:

```python
fields = ["paperId", "title", "year", "url"]
```

Less good:

```python
fields = [
    "paperId",
    "title",
    "abstract",
    "authors",
    "citations",
    "references",
    "embedding",
    "tldr",
    "venue",
    "publicationDate",
]
```

Small responses are faster, cheaper, and easier on the service.

## Batch Before You Fan Out

If you already have a list of paper IDs, prefer batch lookups over N separate detail requests.

General rule:

- search once
- collect IDs
- batch fetch details if the API supports the workflow you need
- cache stable metadata locally

That is much more respectful than repeatedly refetching the same papers one by one.

## Caching Strategy

Semantic Scholar metadata is a good candidate for caching because paper metadata and author records are relatively stable compared with request volume.

Recommended cache targets:

- paper details by `paperId`
- author details by `authorId`
- citation and reference pages for a short TTL
- identical search queries for a short TTL when your application can tolerate slightly stale results

Recommended TTLs:

- paper and author metadata: hours to days
- search results: minutes to hours
- citations or references: minutes to hours, depending on freshness needs

Even a basic in-memory or SQLite cache can reduce traffic dramatically.

## Retry Behavior

Retries should handle transient problems, not hide sustained overload.

Use retries for:

- `429 Too Many Requests`
- network timeouts
- temporary upstream failures such as `502`, `503`, `504`

Do not blindly retry:

- `400 Bad Request`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`

Those usually mean the request itself is wrong or the resource is unavailable.

### `Retry-After`

If the server sends `Retry-After`, respect it. That is better than guessing.

Tenacity helps with retry orchestration, but server-supplied wait times should override your normal schedule when present.

## Avoiding Async Pitfalls

Common mistakes:

1. Creating a new `httpx.AsyncClient` for every request.
2. Applying a semaphore but no global rate limiter.
3. Applying a rate limiter per coroutine instead of per service client.
4. Using exact `1.0s` spacing with no safety margin.
5. Retrying `429` immediately.
6. Launching `asyncio.gather()` over hundreds of paper IDs without batching.

The fix is straightforward: keep one shared client, one shared limiter, and one shared semaphore per application instance.

## Observability

Log enough to know when you are becoming noisy.

Useful metrics:

- request count by endpoint
- response status counts
- `429` count
- average request latency
- retry count
- queue wait time before a request acquires permission to run
- cache hit rate

If `429` responses are non-trivial, your client is too aggressive or you have multiple processes that are not coordinating their budgets.

## Multi-Process and Multi-Worker Deployments

The strictest bug is forgetting that the rate limit applies to the API key, not just a single coroutine.

If you run multiple workers, multiple app instances, or multiple containers with the same API key, they should coordinate.

Options:

- simplest: route Semantic Scholar traffic through a single worker
- better: use a distributed limiter backed by Redis
- safest operationally: give each deployment environment its own API key when policy allows

Without cross-process coordination, each process can behave correctly locally while violating the shared quota globally.

## Practical Request Patterns

### Search then enrich

Good for interactive workflows:

1. call search with a minimal field set
2. show the first page of results
3. fetch extra details only for papers the user actually opens

### Queue-based background enrichment

Good for offline indexing:

1. enqueue paper IDs
2. drain the queue through one shared client
3. store normalized results in your own database
4. resume safely after failures

### Warm cache on startup

Usually a bad idea at this quota unless the warmup set is tiny and important. Avoid startup traffic spikes.

## Local Development Checklist

1. Put the API key in `.env`.
2. Load it with `python-dotenv`.
3. Keep `SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS` above `1.0`.
4. Test with a tiny query set.
5. Confirm logs show no `429` responses.

Example install:

```bash
pip install httpx tenacity python-dotenv
```

## Production Checklist

1. Store the key in a secret manager or runtime environment, not in a file.
2. Reuse a single `httpx.AsyncClient`.
3. Share one limiter across all Semantic Scholar endpoints.
4. Add caching before increasing throughput elsewhere in your app.
5. Monitor `429` rates and retry volume.
6. Coordinate limits across workers if the key is shared.

## Minimal Usage Example

```python
import asyncio


async def main() -> None:
    client = SemanticScholarClient()
    try:
        result = await client.search_papers(
            "retrieval augmented generation",
            limit=5,
            fields=["paperId", "title", "year", "url"],
        )
        for paper in result.get("data", []):
            print(paper.get("title"), paper.get("year"), paper.get("url"))
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

## Summary

The respectful way to use the Semantic Scholar API is simple:

- authenticate with `x-api-key`
- load secrets from environment variables
- keep one shared async client
- enforce one shared, conservative rate limit across all endpoints
- use semaphores to prevent internal fan-out
- use tenacity for transient failures, not as your primary rate limiter
- request fewer fields, batch where possible, and cache aggressively

That approach will keep your integration stable while being meaningfully kinder to Semantic Scholar's infrastructure.
