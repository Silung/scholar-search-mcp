# Scholar Search MCP

A MCP server that integrates the [CORE API v3](https://api.core.ac.uk/docs/v3), [Semantic Scholar API](https://www.semanticscholar.org/product/api), and [arXiv API](https://info.arxiv.org/help/api/user-manual.html) so AI assistants (e.g. Claude, Cursor) can search and fetch academic paper metadata.

## Features

- **Search papers** – Keyword search with **fallback chain**: tries **CORE API** first (no key required; set `CORE_API_KEY` for higher limits), then **Semantic Scholar**, then **arXiv**; optional year and venue filters (venue applies to Semantic Scholar only)
- **Paper details** – Full metadata (title, authors, abstract, citations, etc.)
- **Citations & references** – Papers that cite or are cited by a given paper
- **Author info** – Author profile and paper list
- **Batch lookup** – Fetch up to 500 papers in one call
- **Recommendations** – Similar papers for a given paper

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


| Tool                        | Description                                                  |
| --------------------------- | ------------------------------------------------------------ |
| `search_papers`             | Search by query; optional `limit`, `fields`, `year`, `venue` |
| `get_paper_details`         | Get one paper by ID (DOI, ArXiv ID, S2 ID, or URL)           |
| `get_paper_citations`       | Papers that cite the given paper                             |
| `get_paper_references`      | References of the given paper                                |
| `get_author_info`           | Author profile by ID                                         |
| `get_author_papers`         | Papers by author                                             |
| `get_paper_recommendations` | Similar papers for a given paper                             |
| `batch_get_papers`          | Details for up to 500 paper IDs                              |


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
`bandit`, `black`, and `pre-commit`.

## Guides

- [Agent Handoff](docs/agent-handoff.md) - current repo status, validation commands, and next recommended work for follow-on agents.
- [Semantic Scholar API Guide](docs/semantic-scholar-api-guide.md) - practical guidance for respectful and effective Semantic Scholar API usage with async rate limiting, retries, and `.env`-based local development.

## License

MIT

## Links

- [CORE API v3 Documentation](https://api.core.ac.uk/docs/v3)
- [Semantic Scholar API](https://api.semanticscholar.org/api-docs)
- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html)
