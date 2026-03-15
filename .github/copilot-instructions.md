# GitHub Copilot Instructions

This repository is optimized for the **GitHub cloud coding agent** as the
primary development engine. Treat these instructions as the durable GitHub-side
counterpart to the in-app MCP onboarding resource and planning prompt.

## Start Here

Before changing code, read these files in order:

1. `README.md` for the public MCP surface and validation commands.
2. `docs/golden-paths.md` for the primary user workflows, tool-routing defaults,
   and success signals.
3. `docs/agent-handoff.md` for current repo status, progress snapshots, known
   hotspots, and suggested next steps.

## Development Priorities

- Keep the **default tool surface small and obvious** for low-context agents.
- Preserve the workflow hierarchy:
  - `search_papers` for quick literature discovery
  - `search_papers_bulk` for exhaustive or paginated retrieval
  - `search_papers_match` / `get_paper_details` for known-item lookup
  - `get_paper_citations` / `get_paper_references` for citation chasing
  - `search_authors` → `get_author_info` → `get_author_papers` for author pivots
  - `search_snippets` only as a recovery tool
- Prefer progressive disclosure over adding overlapping entry points.
- Keep provider complexity explainable but mostly hidden behind the brokered path.

## Durable Planning and Progress

- When you change workflow guidance, update the durable docs in the repo, not
  just inline code strings.
- Keep these three surfaces aligned:
  - `scholar_search_mcp/server.py` (`SERVER_INSTRUCTIONS`,
    `AGENT_WORKFLOW_GUIDE`, `plan_scholar_search`)
  - `docs/golden-paths.md`
  - `docs/agent-handoff.md`
- Record meaningful follow-up work in `docs/agent-handoff.md` or
  `docs/golden-paths.md` so future agents inherit context instead of
  rediscovering it.

## Validation Expectations

Install development extras first:

```bash
pip install -e .[dev]
```

Then run:

```bash
python -m pytest
python -m mypy --config-file pyproject.toml
python -m ruff check .
python -m bandit -c pyproject.toml -r scholar_search_mcp
```

Run focused tests early when making localized changes, then rerun the full stack
before finishing.

## Change Style

- Prefer the smallest complete change over broad refactors.
- Add or update tests when you change behavior or durable agent guidance.
- Keep README, onboarding resources, and tests synchronized when the MCP tool
  contract changes.
- Do not remove durable planning/progress/future-work docs; improve them instead.
