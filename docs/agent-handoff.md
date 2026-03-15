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
- `docs/golden-paths.md` records the primary personas, golden paths, and success
  signals for future agent work.
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

- README JSON examples were corrected so users can paste them directly into Claude Desktop config without breaking JSON parsing.
- A CI workflow was added at `.github/workflows/validate.yml` to run the same validation stack on push and pull request.
- Tests were expanded around `CoreApiClient._result_to_paper()` to cover DOI precedence, nested download URL variants, source URL schema variation, metadata normalization, and invalid-result rejection.
- `scholar_search_mcp/server.py` was split into smaller modules while keeping the public facade stable for tests and entrypoints.
- MCP tool routing now uses a dispatch map instead of a long `if`/`elif` chain.
- Tool descriptions, server instructions, onboarding resource text, and the
  planning prompt now encode the primary research workflows more explicitly.
- `README.md` now calls out the default discovery, bulk, known-item, citation,
  and snippet paths for agents.
- `docs/golden-paths.md` now captures planning assumptions, workflow success
  signals, and future workflow-oriented follow-up work.
- `.github/copilot-instructions.md` now tells GitHub Copilot / cloud coding
  agents which docs to read first, which workflows to preserve, and which
  validation commands to run.

## Progress Snapshot

- Baseline validation (`python -m pytest`, `python -m mypy --config-file pyproject.toml`,
  `python -m ruff check .`, and `python -m bandit -c pyproject.toml -r scholar_search_mcp`)
  passed in this environment after installing `.[dev]`.
- The current pass keeps runtime behavior stable and focuses on agent guidance,
  documentation, and tests for tool-selection intent.
- GitHub-native agent instructions should now be kept in sync with runtime
  onboarding guidance whenever workflow defaults change.

## Known Hotspots

- `CoreApiClient._result_to_paper()` remains the densest parsing logic and should keep getting defensive tests before behavior changes.
- The compatibility contract in `scholar_search_mcp/server.py` is now important. Future cleanup should avoid removing re-exported symbols that tests and downstream imports still rely on.
- `pyproject.toml` is the single source of truth for Python dependencies; no parallel runtime dependency file should be reintroduced casually.
- Dependency version ranges remain intentionally loose.

## Suggested Next Steps

1. Add more negative tests for CORE schema drift, especially malformed author shapes, journal fields, and URL containers.
2. Consider moving from per-request `httpx.AsyncClient` creation to shared clients if connection reuse becomes important.
3. Decide whether the compatibility facade in `scholar_search_mcp/server.py` should remain broad or be narrowed with an explicit supported surface.
4. Expand workflow examples in README/resources so each golden path has at least
   one concrete user request and tool sequence.
5. Consider whether workflow-specific tags or annotations should be added to the
   FastMCP tool metadata for even stronger progressive disclosure in IDE agents.
6. Revisit `.github/copilot-instructions.md` whenever the cloud-coding workflow,
   validation stack, or durable planning docs materially change.

## Commit Hygiene

- Keep validation and documentation updates in the same change as the code they describe.
- Prefer commit messages that make the validation or handoff intent obvious to the next reviewer or agent.
