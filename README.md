# Scholar Search MCP

A MCP server that integrates the [Semantic Scholar API](https://www.semanticscholar.org/product/api) and the [arXiv API](https://info.arxiv.org/help/api/user-manual.html) so AI assistants (e.g. Claude, Cursor) can search and fetch academic paper metadata.

## Features

- **Search papers** – Keyword search over **Semantic Scholar** and **arXiv**; optional year and venue filters (venue applies to Semantic Scholar only)
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

```json
{
  "mcpServers": {
    "scholar-search": {
      "command": "python",
      "args": ["-m", "scholar_search_mcp"],
      "env": {}
    }
  }
}
```

If you have the api-key of Semantic Scholar:

```json
{
  "mcpServers": {
    "scholar-search": {
      "command": "python",
      "args": ["-m", "scholar_search_mcp"],
      "env": {
        "SEMANTIC_SCHOLAR_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

### Cursor

Add an MCP server in Cursor settings with the same `command`, `args`, and `env` as above.

### API key (optional)

The Semantic Scholar API works without a key with lower limits. For higher limits:

1. Get an API key from [Semantic Scholar API](https://www.semanticscholar.org/product/api)
2. Set `SEMANTIC_SCHOLAR_API_KEY` in the server `env` as shown above.

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

## License

MIT

## Links

- [Semantic Scholar API](https://api.semanticscholar.org/api-docs)
- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html)

