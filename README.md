# Scholar Search MCP

A FastMCP-based MCP server that integrates the [CORE API v3](https://api.core.ac.uk/docs/v3), [Semantic Scholar API](https://www.semanticscholar.org/product/api), [arXiv API](https://info.arxiv.org/help/api/user-manual.html), and optionally [SerpApi Google Scholar](https://serpapi.com/google-scholar-api) so AI assistants (e.g. Claude, Cursor) can search and fetch academic paper metadata.

The package now uses FastMCP for tool/resource/prompt registration, Pydantic for strict tool inputs and normalized provider payloads, and provider clients organized as expandable subpackages under `scholar_search_mcp/clients/`.

## Features

- **Search papers** – Keyword search with **fallback chain**: tries **CORE API** first (no key required; set `CORE_API_KEY` for higher limits), then **Semantic Scholar**, then optionally **SerpApi Google Scholar** (opt-in paid), then **arXiv**; optional year, venue, and advanced filters (fieldsOfStudy/publicationTypes/openAccessPdf/minCitationCount apply to Semantic Scholar only). Returns a single best-effort page — not paginated.
- **Bulk paper search** – Boolean-syntax search via `/paper/search/bulk` with cursor-based pagination (up to 1,000 papers/call); pass `pagination.nextCursor` as `cursor` for subsequent pages
- **Best-match / autocomplete** – Single best title match and typeahead completions
- **Paper details** – Full metadata (title, authors, abstract, citations, etc.)
- **Citations & references** – Papers that cite or are cited by a given paper; pass `pagination.nextCursor` as `cursor` for subsequent pages
- **Paper authors** – Author listing for a specific paper; pass `pagination.nextCursor` as `cursor` for subsequent pages
- **Author search & batch** – Search authors by name with cursor pagination, or fetch up to 1,000 author profiles in one call
- **Snippet search** – Quote-like text snippet search returning snippet text, paper metadata, and score
- **Batch lookup** – Fetch up to 500 papers in one call
- **Recommendations** – Similar papers via single-seed GET or multi-seed POST
- **Citation formats** – Get MLA, APA, BibTeX, and other citation export formats for a Google Scholar paper (requires SerpApi)
- **Shared rate limiter** – One 1 req/s pacing lock shared across all Semantic Scholar endpoints
- **Structured FastMCP outputs** – Tools return structured content instead of JSON blobs embedded in text
- **Agent onboarding aids** – Ships a workflow guide resource and a planning prompt alongside the tools

## Installation

```bash
pip install scholar-search-mcp
```

## Configuration

### Claude Desktop

Edit the config file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add:

Set notes outside the JSON block so the example remains valid JSON. In the sample below, CORE is disabled and Semantic Scholar plus arXiv are enabled.

```json
{
  "mcpServers": {
    "scholar-search": {
      "command": "python",
      "args": ["-m", "scholar_search_mcp"],
      "env": {
        "SCHOLAR_SEARCH_ENABLE_CORE": "false",
        "SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR": "true",
        "SCHOLAR_SEARCH_ENABLE_ARXIV": "true"
      }
    }
  }
}
```

If you have API keys (optional but recommended for search):

The next example is also valid JSON. It enables all three search providers and supplies API keys for the services that support them.

```json
{
  "mcpServers": {
    "scholar-search": {
      "command": "python",
      "args": ["-m", "scholar_search_mcp"],
      "env": {
        "CORE_API_KEY": "your-core-api-key-here",
        "SEMANTIC_SCHOLAR_API_KEY": "your-semantic-scholar-api-key-here",
        "SCHOLAR_SEARCH_ENABLE_CORE": "true",
        "SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR": "true",
        "SCHOLAR_SEARCH_ENABLE_ARXIV": "true"
      }
    }
  }
}
```

### Cursor

Add an MCP server in Cursor settings with the same `command`, `args`, and `env` as above.

### API keys (optional)

**Search fallback order:** When you call `search_papers`, the server tries sources in order and uses the first that succeeds:

1. **CORE API** – Tried first; works without a key (subject to [rate limits](https://api.core.ac.uk/docs/v3#section/Rate-limits)). Set `CORE_API_KEY` for higher limits ([register](https://core.ac.uk/api-keys/register)).
2. **Semantic Scholar** – Used if CORE fails; works without a key with lower limits. Set `SEMANTIC_SCHOLAR_API_KEY` for higher limits.
3. **SerpApi Google Scholar** – Optional paid provider, skipped by default. Enable with `SCHOLAR_SEARCH_ENABLE_SERPAPI=true` and set `SERPAPI_API_KEY`. See [SerpApi pricing](https://serpapi.com/pricing).
4. **arXiv** – Used as last fallback; no key required.

`search_papers` is a **brokered single-page search**: it returns results from the first provider that succeeds and does **not** support cursor-based pagination. Every response includes a `brokerMetadata` field that makes this contract explicit:

```json
{
  "data": [...],
  "brokerMetadata": {
    "mode": "brokered_single_page",
    "providerUsed": "semantic_scholar",
    "continuationSupported": false
  }
}
```

| Field                  | Description                                                                                          |
| ---------------------- | ---------------------------------------------------------------------------------------------------- |
| `mode`                 | Always `"brokered_single_page"` for `search_papers`.                                                 |
| `providerUsed`         | Which provider supplied the results: `core`, `semantic_scholar`, `serpapi_google_scholar`, `arxiv`, or `none` if no provider returned results. |
| `continuationSupported`| Always `false` — use `search_papers_bulk` for paginated retrieval.                                   |

When SerpApi supplies the results, the response looks like:

```json
{
  "data": [
    {
      "title": "Attention Is All You Need",
      "source": "serpapi_google_scholar",
      "sourceId": "result_id_from_scholar",
      "canonicalId": "10.xxxx/cluster-or-doi",
      "year": 2017,
      "citationCount": 80000
    }
  ],
  "brokerMetadata": {
    "mode": "brokered_single_page",
    "providerUsed": "serpapi_google_scholar",
    "continuationSupported": false
  }
}
```

`brokerMetadata` now also exposes:

- `attemptedProviders` - ordered provider decisions (`returned_results`, `returned_no_results`, `failed`, `skipped`)
- `semanticScholarOnlyFilters` - which requested filters forced the broker to skip non-compatible providers
- `recommendedPaginationTool` - currently always `search_papers_bulk` for exhaustive retrieval

### Enable/disable search channels

Control which sources are used in the `search_papers` fallback chain via environment variables:


| Variable                                 | Default | Description                                                            |
| ---------------------------------------- | ------- | ---------------------------------------------------------------------- |
| `SCHOLAR_SEARCH_ENABLE_CORE`             | `true`  | Use CORE API. Set to `0`, `false`, or `no` to disable.                 |
| `SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR` | `true`  | Use Semantic Scholar.                                                  |
| `SCHOLAR_SEARCH_ENABLE_SERPAPI`          | `false` | Use SerpApi Google Scholar (opt-in, **paid**). Set `SERPAPI_API_KEY`.  |
| `SCHOLAR_SEARCH_ENABLE_ARXIV`            | `true`  | Use arXiv (last-resort free fallback).                                 |

SerpApi is disabled by default to prevent unexpected costs. When enabled without an API key, affected tool calls return a clear error rather than silently failing.

SerpApi-specific filters (`publicationDateOrYear`, `fieldsOfStudy`, `publicationTypes`, `openAccessPdf`, `minCitationCount`) bypass SerpApi in the fallback chain (same behaviour as CORE).

Example: enable SerpApi as an additional coverage fallback:

```json
"env": {
  "SCHOLAR_SEARCH_ENABLE_SERPAPI": "true",
  "SERPAPI_API_KEY": "your-serpapi-key-here"
}
```


Example: CORE and arXiv only (skip Semantic Scholar):

```json
"env": {
  "SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR": "false"
}
```

### Transport configuration

The server defaults to local **stdio** transport, which is the recommended mode for desktop MCP clients. FastMCP also supports remote HTTP deployment:

| Variable | Default | Description |
| --- | --- | --- |
| `SCHOLAR_SEARCH_TRANSPORT` | `stdio` | One of `stdio`, `http`, `streamable-http`, or `sse` |
| `SCHOLAR_SEARCH_HTTP_HOST` | `127.0.0.1` | Host to bind when using an HTTP transport |
| `SCHOLAR_SEARCH_HTTP_PORT` | `8000` | Port to bind when using an HTTP transport |
| `SCHOLAR_SEARCH_HTTP_PATH` | `/mcp` | MCP endpoint path when using an HTTP transport |

Example remote run:

```bash
SCHOLAR_SEARCH_TRANSPORT=streamable-http \
SCHOLAR_SEARCH_HTTP_HOST=0.0.0.0 \
SCHOLAR_SEARCH_HTTP_PORT=8000 \
python -m scholar_search_mcp
```

## Tools


| Tool                             | Description                                                                                              |
| -------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `search_papers`                  | Single-page best-effort search (CORE → Semantic Scholar → SerpApi Google Scholar → arXiv). Optional filters: `limit`, `fields`, `year`, `venue`, `publicationDateOrYear`, `fieldsOfStudy`, `publicationTypes`, `openAccessPdf`, `minCitationCount`. No pagination — for paginated retrieval use `search_papers_bulk`. |
| `search_papers_bulk`             | Paginated bulk paper search (Semantic Scholar) with advanced boolean query syntax (up to 1,000 papers/call). Pass `cursor=pagination.nextCursor` for subsequent pages; `pagination.hasMore` signals more results. |
| `search_papers_match`            | Find the single paper whose title best matches the query string                                          |
| `paper_autocomplete`             | Return paper title completions for a partial query (typeahead)                                           |
| `get_paper_details`              | Get one paper by ID (DOI, ArXiv ID, S2 ID, or URL)                                                      |
| `get_paper_citations`            | Papers that cite the given paper; pass `cursor=pagination.nextCursor` for subsequent pages               |
| `get_paper_references`           | References of the given paper; pass `cursor=pagination.nextCursor` for subsequent pages                  |
| `get_paper_authors`              | Authors of the given paper; pass `cursor=pagination.nextCursor` for subsequent pages                     |
| `get_author_info`                | Author profile by ID                                                                                     |
| `get_author_papers`              | Papers by author; pass `cursor=pagination.nextCursor` for subsequent pages; supports `publicationDateOrYear` |
| `search_authors`                 | Search for authors by name; pass `cursor=pagination.nextCursor` for subsequent pages                     |
| `batch_get_authors`              | Details for up to 1,000 author IDs in one call                                                           |
| `search_snippets`                | Search for matching text snippets across papers; returns snippet text, paper metadata, and score         |
| `get_paper_recommendations`      | Similar papers for a given paper (GET single-seed)                                                       |
| `get_paper_recommendations_post` | Similar papers from positive and negative seed sets (POST multi-seed)                                    |
| `batch_get_papers`               | Details for up to 500 paper IDs                                                                          |
| `get_paper_citation_formats`     | Get citation export formats (MLA, APA, BibTeX, etc.) for a Google Scholar paper. **Requires SerpApi** (`SCHOLAR_SEARCH_ENABLE_SERPAPI=true` + `SERPAPI_API_KEY`). Pass `result_id=paper.scholarResultId` (not `paper.sourceId`) from a `serpapi_google_scholar` result. Single non-paginated response. |


## Resources and prompts

- Resource: `guide://scholar-search/agent-workflows` - compact onboarding guide for choosing tools and following pagination safely
- Prompt: `plan_scholar_search` - reusable planning prompt for literature-search workflows


## Testing with MCP Inspector

```bash
npm install -g @modelcontextprotocol/inspector
mcp-inspector python -m scholar_search_mcp
```

## Development

Install the package with development extras:

```bash
pip install -e .[dev]
```

Project dependencies are declared in `pyproject.toml`; there is no separate runtime `requirements.txt` to keep in sync.

Run the local test suite:

```bash
pytest
```

Install and run the configured pre-commit hooks:

```bash
pre-commit install
pre-commit run --all-files
```

The development extras now include `pytest`, `pytest-asyncio`, `ruff`, `mypy`,
`bandit`, `types-defusedxml`, and `pre-commit`.

GitHub dependency automation is configured for both Python packages and GitHub Actions via Dependabot, with pull requests checked by the dependency review workflow.

For maintainer orientation after the module split, start with `docs/agent-handoff.md`. The public MCP surface stays in `scholar_search_mcp/server.py`, while implementation now lives in `scholar_search_mcp/dispatch.py`, `scholar_search_mcp/search.py`, `scholar_search_mcp/tools.py`, `scholar_search_mcp/runtime.py`, `scholar_search_mcp/models/`, and provider subpackages under `scholar_search_mcp/clients/`.

## Guides

- [Agent Handoff](docs/agent-handoff.md) - current repo status, validation commands, and next recommended work for follow-on agents.
- [Semantic Scholar API Guide](docs/semantic-scholar-api-guide.md) - practical guidance for respectful and effective Semantic Scholar API usage with async rate limiting, retries, and `.env`-based local development.

## License

MIT

## Links

- [CORE API v3 Documentation](https://api.core.ac.uk/docs/v3)
- [Semantic Scholar API](https://api.semanticscholar.org/api-docs)
- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html)
