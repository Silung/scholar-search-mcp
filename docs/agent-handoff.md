# Agent Handoff

This document is the current working handoff for the fork. It is intended to give any follow-on agent enough context to validate the repo, understand the recent hardening work, and continue from the highest-value next steps without re-discovering project state.

## Current Status

- Local development baseline is configured through `pyproject.toml` and `.pre-commit-config.yaml`.
- Search fallback order is `CORE -> Semantic Scholar -> arXiv` for `search_papers`.
- XML parsing uses `defusedxml`.
- README configuration examples are valid JSON.
- GitHub Actions now validates pushes and pull requests.
- `scholar_search_mcp/server.py` is now a compatibility facade over smaller modules.
- Agent-facing workflow guidance now prioritizes quick discovery, exhaustive retrieval,
  citation chasing, known-item lookup, and author pivots.
- `docs/golden-paths.md` records the primary personas, golden paths, concrete example
  flows, and success signals for future agent work.
- `.github/copilot-instructions.md` now gives GitHub-native guidance for Copilot
  and the GitHub cloud coding agent so repo planning expectations are durable
  outside the runtime MCP surface.

## Module Map

- `scholar_search_mcp/__main__.py` is the `python -m` entrypoint.
- `scholar_search_mcp/server.py` is the public MCP facade and compatibility layer used by tests and package entrypoints.
- `scholar_search_mcp/dispatch.py` routes MCP tool calls through a dispatch map.
- `scholar_search_mcp/search.py` owns the `search_papers` fallback chain and merged response helpers.
- `scholar_search_mcp/tools.py` defines MCP tool schemas.
- `scholar_search_mcp/runtime.py` owns stdio startup.
- `scholar_search_mcp/settings.py` contains environment parsing helpers.
- `scholar_search_mcp/clients/` contains provider clients for CORE, Semantic Scholar, and arXiv.
- `scholar_search_mcp/models/common.py` contains shared Pydantic models including `Paper` (with `scholarResultId`).
- `scholar_search_mcp/parsing.py`, `scholar_search_mcp/constants.py`, and `scholar_search_mcp/transport.py` hold shared helper code and compatibility imports.

## Validation Commands

From the project root, install the package with development extras and then run the validation commands inside the repository virtual environment:

```bash
pip install -e .[dev]
```

Then run:

```bash
pre-commit run --all-files
python -m pytest
python -m mypy --config-file pyproject.toml
python -m bandit -c pyproject.toml -r scholar_search_mcp
```

## What Was Added In This Pass

- `Paper.scholarResultId` is now a first-class model field (not just an extra). This
  makes it visible in the JSON schema so agents can discover it without reading long
  tool descriptions. The field is always `None` for non-SerpApi results.
- `BrokerMetadata.nextStepHint` was added as a new field. The `_metadata()` helper
  in `search.py` now populates it with provider-specific guidance:
  - For `serpapi_google_scholar` results: hints that `paper.scholarResultId` can be
    passed to `get_paper_citation_formats`.
  - For "none" results: hints to broaden the query or try `search_papers_bulk`.
  - For all other results: hints to use `search_papers_bulk` or citation expansion.
- `SERVER_INSTRUCTIONS` was restructured as a numbered decision tree for faster
  agent scanning: QUICK DISCOVERY → EXHAUSTIVE → KNOWN ITEM → CITATION → AUTHOR → SNIPPET.
- `AGENT_WORKFLOW_GUIDE` was rewritten with a quick-decision-table format under
  `guide://scholar-search/agent-workflows`.
- `plan_scholar_search` prompt was updated to reference `brokerMetadata.nextStepHint`.
- `docs/golden-paths.md` now includes concrete example requests and tool sequences
  for each golden path.

## Progress Snapshot

- Baseline validation (`python -m pytest`, `python -m mypy --config-file pyproject.toml`,
  `python -m ruff check .`, and `python -m bandit -c pyproject.toml -r scholar_search_mcp`)
  passed in this environment after installing `.[dev]`.
- The current pass keeps runtime behavior stable and focuses on schema discoverability,
  structured hints, and tighter agent guidance.

## Known Hotspots

- `CoreApiClient._result_to_paper()` remains the densest parsing logic and should keep getting defensive tests before behavior changes.
- The compatibility contract in `scholar_search_mcp/server.py` is now important. Future cleanup should avoid removing re-exported symbols that tests and downstream imports still rely on.
- `pyproject.toml` is the single source of truth for Python dependencies; no parallel runtime dependency file should be reintroduced casually.
- Dependency version ranges remain intentionally loose.

## Suggested Next Steps

1. Add more negative tests for CORE schema drift, especially malformed author shapes, journal fields, and URL containers.
2. Consider moving from per-request `httpx.AsyncClient` creation to shared clients if connection reuse becomes important.
3. Decide whether the compatibility facade in `scholar_search_mcp/server.py` should remain broad or be narrowed with an explicit supported surface.
4. Revisit `.github/copilot-instructions.md` whenever the cloud-coding workflow,
   validation stack, or durable planning docs materially change.
5. Add a success-metric test that asserts `brokerMetadata.nextStepHint` is visible in responses and varies by provider.

## Commit Hygiene

- Keep validation and documentation updates in the same change as the code they describe.
- Prefer commit messages that make the validation or handoff intent obvious to the next reviewer or agent.
