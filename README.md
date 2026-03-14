# Scholar Search MCP

A MCP server that integrates the [CORE API v3](https://api.core.ac.uk/docs/v3), [Semantic Scholar API](https://www.semanticscholar.org/product/api), and [arXiv API](https://info.arxiv.org/help/api/user-manual.html) so AI assistants (e.g. Claude, Cursor) can search and fetch academic paper metadata.

The package now uses Pydantic for tool inputs, settings, and normalized provider payloads, and the provider clients are organized as expandable subpackages under `scholar_search_mcp/clients/`.

## Features

- **Search papers** – Keyword search with **fallback chain**: tries **CORE API** first (no key required; set `CORE_API_KEY` for higher limits), then **Semantic Scholar**, then **arXiv**; optional year, venue, and advanced filters (venue/fieldsOfStudy/publicationTypes/openAccessPdf/minCitationCount apply to Semantic Scholar only)
- **Bulk paper search** – Boolean-syntax search via `/paper/search/bulk` with token-based pagination (up to 1,000 papers/call)
- **Best-match / autocomplete** – Single best title match and typeahead completions
- **Paper details** – Full metadata (title, authors, abstract, citations, etc.)
- **Citations & references** – Papers that cite or are cited by a given paper
- **Paper authors** – Author listing for a specific paper with offset pagination
- **Author search & batch** – Search authors by name, or fetch up to 1,000 author profiles in one call
- **Snippet search** – Quote-like text snippet search returning snippet text, paper metadata, and score
- **Batch lookup** – Fetch up to 500 papers in one call
- **Recommendations** – Similar papers via single-seed GET or multi-seed POST
- **Shared rate limiter** – One 1 req/s pacing lock shared across all Semantic Scholar endpoints

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
3. **arXiv** – Used as last fallback; no key required.

### Enable/disable search channels

Control which sources are used in the `search_papers` fallback chain via environment variables (default: all enabled):


| Variable                                 | Description                                                            |
| ---------------------------------------- | ---------------------------------------------------------------------- |
| `SCHOLAR_SEARCH_ENABLE_CORE`             | Use CORE API (default: true). Set to `0`, `false`, or `no` to disable. |
| `SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR` | Use Semantic Scholar (default: true).                                  |
| `SCHOLAR_SEARCH_ENABLE_ARXIV`            | Use arXiv (default: true).                                             |


Example: CORE and arXiv only (skip Semantic Scholar):

```json
"env": {
  "SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR": "false"
}
```

## Tools


| Tool                             | Description                                                                                              |
| -------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `search_papers`                  | Search by query; optional `limit`, `fields`, `year`, `venue`, `offset`, `publicationDateOrYear`, `fieldsOfStudy`, `publicationTypes`, `openAccessPdf`, `minCitationCount` |
| `search_papers_bulk`             | Bulk paper search with advanced boolean query syntax and token-based pagination (up to 1,000 papers/call) |
| `search_papers_match`            | Find the single paper whose title best matches the query string                                          |
| `paper_autocomplete`             | Return paper title completions for a partial query (typeahead)                                           |
| `get_paper_details`              | Get one paper by ID (DOI, ArXiv ID, S2 ID, or URL)                                                      |
| `get_paper_citations`            | Papers that cite the given paper; supports `offset` pagination                                           |
| `get_paper_references`           | References of the given paper; supports `offset` pagination                                              |
| `get_paper_authors`              | Authors of the given paper; supports `offset` pagination                                                 |
| `get_author_info`                | Author profile by ID                                                                                     |
| `get_author_papers`              | Papers by author; supports `offset` and `publicationDateOrYear`                                         |
| `search_authors`                 | Search for authors by name; supports `offset` pagination                                                 |
| `batch_get_authors`              | Details for up to 1,000 author IDs in one call                                                           |
| `search_snippets`                | Search for matching text snippets across papers; returns snippet text, paper metadata, and score         |
| `get_paper_recommendations`      | Similar papers for a given paper (GET single-seed)                                                       |
| `get_paper_recommendations_post` | Similar papers from positive and negative seed sets (POST multi-seed)                                    |
| `batch_get_papers`               | Details for up to 500 paper IDs                                                                          |


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
