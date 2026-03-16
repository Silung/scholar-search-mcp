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
- The highest-priority workflow-level rough edges from the last agent UX review
  have now been fixed in code, tests, and durable docs.

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
- `search_papers_match` now normalizes wrapped Semantic Scholar match responses
  to one clean paper-shaped payload.
- CORE search now follows redirects so the default broker path does not record
  an avoidable failed first provider attempt for predictable 301s.
- `brokerMetadata.nextStepHint` now distinguishes between the closest
  continuation path and a Semantic Scholar/provider pivot.
- Provider-specific search tool schemas now expose only the parameters their
  providers actually honor.
- Success-metric tests now lock workflow cues into tool descriptions, runtime
  onboarding resources, prompt text, and `.github/copilot-instructions.md`.
- CORE search now retries short-lived 5xx responses, which was required after
  live broker smoke testing exposed transient backend shard failures on the
  first hop.

## Progress Snapshot

- Baseline validation (`python -m pytest`, `python -m mypy --config-file pyproject.toml`,
  `python -m ruff check .`, and `python -m bandit -c pyproject.toml -r scholar_search_mcp`)
  passed in this environment after installing `.[dev]`.
- The current pass keeps runtime behavior stable and focuses on schema discoverability,
  structured hints, and tighter agent guidance.
- The highest-impact UX issues from the last live agent pass were addressed with
  targeted runtime fixes and regression coverage.
- Current follow-up work is now mostly product-shaping work around provider
  preferences and whether retry-recovered provider behavior should be surfaced
  to agents.
- A live broker smoke test was completed against the configured providers in
  this workspace. It confirmed the new hint wording live and exposed a
  transient CORE 500, which is now mitigated by short retries in the client.

## Follow-up Completed

1. `search_papers_match` response-shape ambiguity is fixed.
  Wrapped Semantic Scholar match responses are now normalized to one clean
  paper payload, and regression tests cover both direct client normalization and
  FastMCP structured output.

2. The default `search_papers` broker path now follows predictable CORE
  redirects.
  CORE requests explicitly follow redirects so avoidable 301-driven broker
  failures do not pollute `brokerMetadata.attemptedProviders`.

3. `brokerMetadata.nextStepHint` now distinguishes continuation from pivots.
  Semantic Scholar responses describe bulk retrieval as the closest
  continuation path when appropriate, while CORE/arXiv/SerpApi responses label
  it as a Semantic Scholar pivot. Venue-filtered searches explicitly warn that
  bulk retrieval broadens semantics.

4. Provider-specific search schemas no longer over-advertise unsupported
  filters.
  CORE, SerpApi, and arXiv tool schemas now expose only `query`, `limit`, and
  `year`, while the Semantic Scholar-only tool retains the broader compatible
  filter set.

5. Live broker smoke coverage is complete for the current environment.
  A fresh process using the workspace MCP config exercised the default broker
  path, a SerpApi-preferred path, and a venue-filtered Semantic Scholar path.
  The hint wording behaved as intended live, and the CORE path now survives
  transient backend 500s by retrying before falling through.

## Known Hotspots

- `CoreApiClient._result_to_paper()` remains the densest parsing logic and should keep getting defensive tests before behavior changes.
- The compatibility contract in `scholar_search_mcp/server.py` is now important. Future cleanup should avoid removing re-exported symbols that tests and downstream imports still rely on.
- `pyproject.toml` is the single source of truth for Python dependencies; no parallel runtime dependency file should be reintroduced casually.
- Dependency version ranges remain intentionally loose.
- `search.py::_metadata()` now carries product-level UX weight because agents use `nextStepHint` as operational guidance rather than decorative metadata.

## Suggested Next Steps

1. Consider whether budget-aware provider preferences should become a more explicit first-class planning concept in the docs and prompt surfaces.
2. Decide whether retry-recovered provider behavior should remain invisible or become broker metadata.
3. Revisit `.github/copilot-instructions.md` and `docs/golden-paths.md` whenever future agent-facing search behavior materially changes.

## Ready Handoff Prompt

Use this prompt for the next agent if the goal is to act on the UX review directly:

```text
You are picking up scholar-search-mcp after an agent UX review. Read README.md, docs/golden-paths.md, and docs/agent-handoff.md first.

Focus on the remaining agent-facing follow-up after the recent UX fixes:
1. Revisit budget-aware provider steering if future UX work needs stronger source control.
2. Decide whether retry-recovered provider behavior should remain invisible or become broker metadata.
3. Keep the durable onboarding surfaces aligned if the workflow contract changes again.

Your task:
- Inspect the broker, onboarding, and durable-doc surfaces that describe the
  intended workflow contract.
- Implement the smallest complete change you can defend for any remaining
  provider-steering or metadata decision you touch.
- Add or update targeted tests and durable docs if the agent-facing behavior changes again.

Validation target:
- python -m pytest
- python -m mypy --config-file pyproject.toml
- python -m ruff check .
- python -m bandit -c pyproject.toml -r scholar_search_mcp

Do not broaden scope unless a blocking dependency makes it necessary.
```

## Commit Hygiene

- Keep validation and documentation updates in the same change as the code they describe.
- Prefer commit messages that make the validation or handoff intent obvious to the next reviewer or agent.
