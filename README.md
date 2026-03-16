# Scholar Search MCP

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/joshuasundance-swca/scholar-search-mcp)

A FastMCP-based MCP server that integrates the [CORE API v3](https://api.core.ac.uk/docs/v3), [Semantic Scholar API](https://www.semanticscholar.org/product/api), [arXiv API](https://info.arxiv.org/help/api/user-manual.html), and optionally [SerpApi Google Scholar](https://serpapi.com/google-scholar-api) so AI assistants (e.g. Claude, Cursor) can search and fetch academic paper metadata.

The package now uses FastMCP for tool/resource/prompt registration, Pydantic for strict tool inputs and normalized provider payloads, and provider clients organized as expandable subpackages under `scholar_search_mcp/clients/`.

## Features

- **Search papers** – Keyword search with a configurable **fallback chain**: defaults to **CORE API** first (no key required; set `CORE_API_KEY` for higher limits), then **Semantic Scholar**, then optionally **SerpApi Google Scholar** (opt-in paid), then **arXiv**. You can keep the default broker behavior, set a `preferredProvider`, override `providerOrder`, or call provider-specific `search_papers_*` tools directly. Returns a single best-effort page — not paginated.
- **Bulk paper search** – Boolean-syntax search via `/paper/search/bulk` with cursor-based pagination (up to 1,000 returned papers/call). The upstream bulk endpoint may ignore small `limit` values internally, so this server truncates returned data to the requested limit; use `search_papers` or `search_papers_semantic_scholar` for small targeted pages. Treat `pagination.nextCursor` as opaque and pass it back unchanged as `cursor`
- **Best-match / autocomplete** – Single best title match and typeahead completions
- **Paper details** – Full metadata (title, authors, abstract, citations, etc.)
- **Citations & references** – Papers that cite or are cited by a given paper; treat `pagination.nextCursor` as opaque and pass it back unchanged as `cursor`
- **Paper authors** – Author listing for a specific paper; treat `pagination.nextCursor` as opaque and pass it back unchanged as `cursor`
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

### Pagination cursor contract

For every paginated tool:

- `pagination.nextCursor` is an **opaque** server-issued token
- pass it back as `cursor` **exactly as returned**
- do **not** derive, edit, increment, or fabricate it
- do **not** reuse it across a different tool or different query flow

The server validates those boundaries and returns an actionable `INVALID_CURSOR`
error if a cursor is malformed, cross-tool, or stale for the current query
context.

### API keys (optional)

**Default search fallback order:** When you call `search_papers`, the server tries sources in order and uses the first that succeeds:

1. **CORE API** – Tried first; works without a key (subject to [rate limits](https://api.core.ac.uk/docs/v3#section/Rate-limits)). Set `CORE_API_KEY` for higher limits ([register](https://core.ac.uk/api-keys/register)).
2. **Semantic Scholar** – Used if CORE fails; works without a key with lower limits. Set `SEMANTIC_SCHOLAR_API_KEY` for higher limits.
3. **SerpApi Google Scholar** – Optional paid provider, skipped by default. Enable with `SCHOLAR_SEARCH_ENABLE_SERPAPI=true` and set `SERPAPI_API_KEY`. See [SerpApi pricing](https://serpapi.com/pricing).
4. **arXiv** – Used as last fallback; no key required.

`search_papers` is a **brokered single-page search**: it returns results from the first provider in the effective chain that succeeds and does **not** support cursor-based pagination. By default the effective chain is the order above, but you can:

- set `preferredProvider` to try one provider first and then fall back through the rest of the configured chain
- set `providerOrder` to override the provider chain for a single call (omitted providers are skipped for that request)
- set `SCHOLAR_SEARCH_PROVIDER_ORDER` to override the default broker order for a deployment
- use `search_papers_core`, `search_papers_semantic_scholar`, `search_papers_serpapi`, or `search_papers_arxiv` for single-provider searches

Provider names accepted in `preferredProvider`, `providerOrder`, and `SCHOLAR_SEARCH_PROVIDER_ORDER` are `core`, `semantic_scholar`, `arxiv`, and either `serpapi` or `serpapi_google_scholar`. Broker metadata continues to report the SerpApi provider as `serpapi_google_scholar`.

Every response includes a `brokerMetadata` field that makes this contract explicit:

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

#### Cross-provider paper ID portability

Brokered `search_papers` results normalize metadata across providers, but raw
provider IDs are **not automatically portable** into Semantic Scholar expansion
tools such as `get_paper_citations`, `get_paper_references`, `get_paper_authors`,
or the author-pivot flow that follows them. When a brokered result did **not**
come from Semantic Scholar:

- prefer `paper.recommendedExpansionId` when it is present
- check `paper.expansionIdStatus` before reusing any returned identifier
- if `paper.expansionIdStatus` is `not_portable`, do **not** retry with
  brokered `paperId`, `sourceId`, or `canonicalId`; resolve the paper through a
  DOI or a Semantic Scholar-native lookup first

This matters for brokered CORE results in particular: when no DOI is available,
`paper.canonicalId` may still be only a CORE-native identifier rather than a
Semantic Scholar-compatible expansion ID.

#### Provider order and filter-based skipping

Provider order controls *which providers are eligible and in what order they are attempted*, but compatibility rules still apply. If you request Semantic Scholar-only filters such as `publicationDateOrYear`, `fieldsOfStudy`, `publicationTypes`, `openAccessPdf`, or `minCitationCount`, the broker will skip `core` and `serpapi(_google_scholar)` even if they appear earlier in `providerOrder`. Example: `providerOrder=["core","semantic_scholar","arxiv"]` with `publicationDateOrYear="2020:2024"` will skip CORE and continue to Semantic Scholar because CORE cannot honor that filter.

### Enable/disable search channels

Control which sources are used in the `search_papers` fallback chain via environment variables:


| Variable                                 | Default | Description                                                            |
| ---------------------------------------- | ------- | ---------------------------------------------------------------------- |
| `SCHOLAR_SEARCH_ENABLE_CORE`             | `true`  | Use CORE API. Set to `0`, `false`, or `no` to disable.                 |
| `SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR` | `true`  | Use Semantic Scholar.                                                  |
| `SCHOLAR_SEARCH_ENABLE_SERPAPI`          | `false` | Use SerpApi Google Scholar (opt-in, **paid**). Set `SERPAPI_API_KEY`.  |
| `SCHOLAR_SEARCH_ENABLE_ARXIV`            | `true`  | Use arXiv (last-resort free fallback).                                 |
| `SCHOLAR_SEARCH_PROVIDER_ORDER`          | `core,semantic_scholar,serpapi_google_scholar,arxiv` | Comma-separated default broker order for `search_papers`. Omit a provider to remove it from the default broker chain. Accepts `serpapi` as a shorthand for `serpapi_google_scholar`. |

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

Example: prefer Semantic Scholar first, then arXiv for this deployment:

```json
"env": {
  "SCHOLAR_SEARCH_PROVIDER_ORDER": "semantic_scholar,arxiv"
}
```

### Transport configuration

The server defaults to local **stdio** transport, which is the recommended mode for desktop MCP clients. FastMCP also supports HTTP-compatible transports for local development, integration testing, and controlled deployments:

| Variable | Default | Description |
| --- | --- | --- |
| `SCHOLAR_SEARCH_TRANSPORT` | `stdio` | One of `stdio`, `http`, `streamable-http`, or `sse` |
| `SCHOLAR_SEARCH_HTTP_HOST` | `127.0.0.1` | Host to bind when using an HTTP transport |
| `SCHOLAR_SEARCH_HTTP_PORT` | `8000` | Port to bind when using an HTTP transport |
| `SCHOLAR_SEARCH_HTTP_PATH` | `/mcp` | MCP endpoint path when using an HTTP transport |

> [!IMPORTANT]
> HTTP transport compatibility is available, but this repository does **not**
> yet ship a hardened public deployment profile. Before exposing the server
> beyond localhost, add Origin validation/allowlisting, authentication, and
> TLS in front of the ASGI app. This follows the MCP HTTP transport guidance
> confirmed via Context7: servers must validate `Origin` and should implement
> authentication for HTTP transports.

Use `scholar_search_mcp.server.build_http_app(...)` if you need to inject
deployment-specific Starlette middleware around the FastMCP ASGI app.

Example local/integration HTTP run:

```bash
SCHOLAR_SEARCH_TRANSPORT=streamable-http \
SCHOLAR_SEARCH_HTTP_HOST=0.0.0.0 \
SCHOLAR_SEARCH_HTTP_PORT=8000 \
python -m scholar_search_mcp
```

## Tools

Primary defaults for agents:

- Start with `search_papers` for quick literature discovery.
- Switch to `search_papers_bulk` for exhaustive retrieval or multi-page collection.
- For small targeted pages, prefer `search_papers` or `search_papers_semantic_scholar` instead of `search_papers_bulk`.
- Use `search_papers_match` or `get_paper_details` for known-item lookup.
- Expand with `get_paper_citations`, `get_paper_references`, and `search_authors`
  once you have a paper or author anchor.
- Reach for `search_snippets` only when quote or phrase recovery is needed.


| Tool                             | Description                                                                                              |
| -------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `search_papers`                  | Primary entry point for quick literature discovery. Single-page best-effort brokered search. Default order: CORE → Semantic Scholar → SerpApi Google Scholar → arXiv. Use `brokerMetadata` to see where results came from and decide whether to broaden, narrow, paginate, or pivot. Optional filters: `limit`, `fields`, `year`, `venue`, `preferredProvider`, `providerOrder`, `publicationDateOrYear`, `fieldsOfStudy`, `publicationTypes`, `openAccessPdf`, `minCitationCount`. No pagination — for paginated retrieval use `search_papers_bulk`. |
| `search_papers_core`             | Single-page CORE-only search with the same normalized response shape as `search_papers`. Exposes only the inputs CORE actually honors: `query`, `limit`, and `year`. |
| `search_papers_semantic_scholar` | Single-page Semantic Scholar-only search with the same normalized response shape as `search_papers`. Exposes the Semantic Scholar-compatible inputs: `query`, `limit`, `fields`, `year`, `venue`, `publicationDateOrYear`, `fieldsOfStudy`, `publicationTypes`, `openAccessPdf`, and `minCitationCount`. |
| `search_papers_serpapi`          | Single-page SerpApi Google Scholar-only search. **Requires SerpApi** (`SCHOLAR_SEARCH_ENABLE_SERPAPI=true` + `SERPAPI_API_KEY`). Exposes only the inputs SerpApi actually honors: `query`, `limit`, and `year`. |
| `search_papers_arxiv`            | Single-page arXiv-only search with the same normalized response shape as `search_papers`. Exposes only the inputs arXiv actually honors: `query`, `limit`, and `year`. |
| `search_papers_bulk`             | Primary exhaustive retrieval tool. Paginated bulk paper search (Semantic Scholar) with advanced boolean query syntax (up to 1,000 returned papers/call). The upstream bulk endpoint may ignore small `limit` values internally, so this server truncates returned data to the requested limit; prefer `search_papers` or `search_papers_semantic_scholar` for small targeted pages. Treat `pagination.nextCursor` as opaque, pass it back unchanged as `cursor`, and do not derive/edit/fabricate it; `pagination.hasMore` signals more results. |
| `search_papers_match`            | Known-item lookup for messy or partial titles; finds the single paper whose title best matches the query string, falls back to fuzzy Semantic Scholar title search on exact-match 400/404 misses, and returns a structured no-match payload when the item still cannot be recovered |
| `paper_autocomplete`             | Return paper title completions for a partial query (typeahead)                                           |
| `get_paper_details`              | Known-item lookup by identifier: get one paper by DOI, ArXiv ID, S2 ID, or URL                         |
| `get_paper_citations`            | Citation chasing outward: papers that cite the given paper (`cited by`); for Semantic Scholar expansion prefer `paper.recommendedExpansionId`, and if `paper.expansionIdStatus` is `not_portable` resolve the paper through DOI or a Semantic Scholar-native lookup before expanding; treat `pagination.nextCursor` as opaque, pass it back unchanged as `cursor`, and keep it scoped to the same tool/query flow |
| `get_paper_references`           | Citation chasing backward: references behind the given paper; for Semantic Scholar expansion prefer `paper.recommendedExpansionId`, and if `paper.expansionIdStatus` is `not_portable` resolve the paper through DOI or a Semantic Scholar-native lookup before expanding; treat `pagination.nextCursor` as opaque, pass it back unchanged as `cursor`, and keep it scoped to the same tool/query flow |
| `get_paper_authors`              | Authors of the given paper; for this Semantic Scholar expansion path prefer `paper.recommendedExpansionId`, and if `paper.expansionIdStatus` is `not_portable` resolve the paper through DOI or a Semantic Scholar-native lookup before expanding; treat `pagination.nextCursor` as opaque, pass it back unchanged as `cursor`, and keep it scoped to the same tool/query flow |
| `get_author_info`                | Author profile by Semantic Scholar author ID (typically from `search_authors` or `get_paper_authors`)   |
| `get_author_papers`              | Papers by author; requires a Semantic Scholar author ID; treat `pagination.nextCursor` as opaque, pass it back unchanged as `cursor`, and keep it scoped to the same tool/query flow; supports `publicationDateOrYear` |
| `search_authors`                 | Search for authors by name using a plain-text query; the server normalizes exact-name punctuation before calling Semantic Scholar, and common-name workflows should add affiliation, coauthor, venue, or topic clues before confirming the best candidate; treat `pagination.nextCursor` as opaque, pass it back unchanged as `cursor`, and keep it scoped to the same tool/query flow |
| `batch_get_authors`              | Details for up to 1,000 author IDs in one call                                                           |
| `search_snippets`                | Special-purpose recovery tool for quote or phrase validation when title/keyword search is weak; returns snippet text, paper metadata, and score, and degrades provider 4xx/5xx failures to an empty result with retry guidance |
| `get_paper_recommendations`      | Similar papers for a given paper (GET single-seed)                                                       |
| `get_paper_recommendations_post` | Similar papers from positive and negative seed sets (POST multi-seed)                                    |
| `batch_get_papers`               | Details for up to 500 paper IDs                                                                          |
| `get_paper_citation_formats`     | Citation export step for MLA, APA, BibTeX, etc. from a Google Scholar paper. **Requires SerpApi** (`SCHOLAR_SEARCH_ENABLE_SERPAPI=true` + `SERPAPI_API_KEY`). Pass `result_id=paper.scholarResultId` (not `paper.sourceId`) from a `serpapi_google_scholar` result. Single non-paginated response. |


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

### GitHub Agentic Workflow smoke test

The repository now includes an agentic regression workflow source at
`.github/workflows/test-scholar-search.md` and its compiled lock file at
`.github/workflows/test-scholar-search.lock.yml`. After editing the Markdown
workflow, recompile it and then run the normal validation stack so pre-commit
can normalize the generated lock file:

```bash
gh aw compile test-scholar-search --dir .github/workflows
```

What this workflow does:

- Runs GitHub Copilot as the workflow engine against the local `scholar-search`
  MCP server inside GitHub Actions.
- Exercises the primary golden paths instead of every tool: quick discovery,
  known-item lookup, bulk pagination, citation chasing, author pivot, and
  optional SerpApi citation export.
- Produces a high-level smoke test that catches agent-facing workflow regressions
  that unit tests can miss.

How it runs in GitHub:

- The editable source of truth is `.github/workflows/test-scholar-search.md`.
- `gh aw compile ...` generates `.github/workflows/test-scholar-search.lock.yml`,
  which is the Actions workflow file GitHub actually runs.
- Once both files are committed to the default branch and the required secrets
  are configured, GitHub can run the workflow on its schedule or when manually
  triggered with `workflow_dispatch` from the Actions tab.

Required secrets for this workflow:

- `COPILOT_GITHUB_TOKEN` is required. The GitHub Copilot CLI engine fails in
  the activation job before the repo checkout or MCP startup steps if this
  secret is not present.
- `CORE_API_KEY` is optional.
- `SEMANTIC_SCHOLAR_API_KEY` is optional.

How to update and use it:

1. Edit `.github/workflows/test-scholar-search.md`.
2. Recompile it with `gh aw compile test-scholar-search --dir .github/workflows`.
3. Run the normal validation stack so pre-commit can normalize the generated
   lock file.
4. Commit both the `.md` source and `.lock.yml` output together.
5. Push the branch, then run `Test Scholar Search MCP` from the GitHub Actions
   UI or wait for the scheduled run on the default branch.

The normal `Validate` workflow now also recompiles `test-scholar-search.md` on
CI and fails if `.github/workflows/test-scholar-search.lock.yml` is stale, so
pull requests cannot silently drift out of sync.

For this repo, there is no separate deployment step beyond checking in the
workflow source and compiled lock file. The workflow is "deployed" when GitHub
Actions sees the committed `.lock.yml` on the branch where it should run.

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

- [GitHub Copilot Instructions](.github/copilot-instructions.md) - repo-specific guidance for GitHub Copilot and the GitHub cloud coding agent, including workflow defaults and durable planning expectations.
- [Agent Handoff](docs/agent-handoff.md) - current repo status, validation commands, and next recommended work for follow-on agents.
- [Scholar Search Golden Paths](docs/golden-paths.md) - primary personas, workflow defaults, success signals, and future workflow-oriented follow-up work.
- [Semantic Scholar API Guide](docs/semantic-scholar-api-guide.md) - practical guidance for respectful and effective Semantic Scholar API usage with async rate limiting, retries, and `.env`-based local development.

## License

MIT

## Links

- [CORE API v3 Documentation](https://api.core.ac.uk/docs/v3)
- [Semantic Scholar API](https://api.semanticscholar.org/api-docs)
- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html)
