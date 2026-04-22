# Scholar Search MCP

A MCP server that integrates the [Semantic Scholar API](https://www.semanticscholar.org/product/api) and [arXiv API](https://info.arxiv.org/help/api/user-manual.html) so AI assistants (e.g. Claude, Cursor) can search and fetch academic paper metadata.

## Features

- **Search papers** – Keyword search with parallel merge from **Semantic Scholar** and **arXiv**; optional year and venue filters (venue applies to Semantic Scholar only)
- **Paper details** – Full metadata (title, authors, abstract, citations, etc.)
- **Citations & references** – Papers that cite or are cited by a given paper
- **Author info** – Author profile and paper list
- **Batch lookup** – Fetch up to 500 papers in one call
- **Recommendations** – Similar papers for a given paper
- **arXiv LaTeX source** – Download and extract the source tarball from `https://arxiv.org/src/{id}` (tool: `download_arxiv_source`)

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
      "env": {
        "SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR": "true", // enable https://www.semanticscholar.org/
        "SCHOLAR_SEARCH_ENABLE_ARXIV": "true" // enable https://arxiv.org/
      }
    }
  }
}
```

If you have API keys (optional but recommended for search):

```json
{
  "mcpServers": {
    "scholar-search": {
      "command": "python",
      "args": ["-m", "scholar_search_mcp"],
      "env": {
        "SEMANTIC_SCHOLAR_API_KEY": "your-semantic-scholar-api-key-here",
        "SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR": "true", // enable https://www.semanticscholar.org/
        "SCHOLAR_SEARCH_ENABLE_ARXIV": "true" // enable https://arxiv.org/
      }
    }
  }
}
```

### Cursor

Add an MCP server in Cursor settings with the same `command`, `args`, and `env` as above.

### API keys (optional)

`search_papers` queries enabled sources in parallel and merges results by title:

1. **Semantic Scholar** – Works without a key with lower limits. Set `SEMANTIC_SCHOLAR_API_KEY` for higher limits.
2. **arXiv** – No key required.

### Enable/disable search channels

Control which sources are used in `search_papers` via environment variables (default: all enabled):


| Variable                                 | Description                           |
| ---------------------------------------- | ------------------------------------- |
| `SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR` | Use Semantic Scholar (default: true). |
| `SCHOLAR_SEARCH_ENABLE_ARXIV`            | Use arXiv (default: true).            |

Example: CORE and arXiv only (skip Semantic Scholar):

```json
"env": {
  "SCHOLAR_SEARCH_ENABLE_SEMANTIC_SCHOLAR": "false"
}
```

### arXiv source downloads (`download_arxiv_source`)

Optional default **parent** directory for extracted sources when the tool is called without `output_dir`:

| Variable                    | Description                                                                 |
| --------------------------- | ----------------------------------------------------------------------------- |
| `SCHOLAR_ARXIV_SOURCE_DIR` | If set, files go under `<dir>/<arxiv_id>/`. Otherwise uses a temp subfolder. |

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
| `download_arxiv_source`     | Download arXiv source `tar.gz` and extract; args: `arxiv_id`, optional `output_dir` |


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

