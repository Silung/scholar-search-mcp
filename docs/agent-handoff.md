# Agent Handoff

This document is the current working handoff for the fork. It is intended to give any follow-on agent enough context to validate the repo, understand the recent hardening work, and continue from the highest-value next steps without re-discovering project state.

## Current Status

- Local development baseline is configured through `pyproject.toml` and `.pre-commit-config.yaml`.
- Search fallback order is `CORE -> Semantic Scholar -> arXiv` for `search_papers`.
- XML parsing uses `defusedxml`.
- README configuration examples are valid JSON.
- GitHub Actions now validates pushes and pull requests.

## Validation Commands

Run these commands from the project root inside the repository virtual environment:

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

## Known Hotspots

- `scholar_search_mcp/server.py` still combines clients, normalization, tool definitions, dispatch, and startup wiring.
- `call_tool()` still uses an `if`/`elif` chain instead of a dispatch map.
- `CoreApiClient._result_to_paper()` remains the densest parsing logic and should keep getting defensive tests before behavior changes.
- Dependency version ranges remain intentionally loose.

## Suggested Next Steps

1. Split `scholar_search_mcp/server.py` into smaller modules such as `clients`, `handlers`, and `config`.
2. Replace the `call_tool()` branching chain with a dispatch map to simplify extension and testing.
3. Add more negative tests for CORE schema drift, especially malformed author shapes, journal fields, and URL containers.
4. Decide whether `requirements.txt` should remain alongside `pyproject.toml` or be removed as a duplicated dependency source.

## Commit Hygiene

- Keep validation and documentation updates in the same change as the code they describe.
- Prefer commit messages that make the validation or handoff intent obvious to the next reviewer or agent.