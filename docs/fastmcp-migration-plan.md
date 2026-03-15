# FastMCP migration analysis for `scholar-search-mcp`

This document ties the recommended FastMCP design directly to the current repository implementation. It is intended to help maintainers understand what was preserved, what was redesigned, and what should come next.

## Context7-backed decisions used here

- **FastMCP server framework**: Context7-confirmed FastMCP patterns support `FastMCP(...)`, `@mcp.tool`, `@mcp.resource`, `@mcp.prompt`, `mcp.run(...)`, `mcp.http_app(...)`, in-memory client testing with `Client(server)`, and middleware such as `TimingMiddleware`.
- **Structured tool output**: Context7-confirmed FastMCP tools can return dictionaries or typed models and FastMCP will expose structured content to clients instead of forcing agents to parse JSON blobs from text.
- **Transport guidance**: Context7-confirmed MCP transport guidance still centers on `stdio` for local subprocess use and Streamable HTTP for remote deployment. The MCP spec also warns that HTTP servers should validate `Origin`, bind locally when appropriate, and use proper authentication.
- **Prompt/resource discoverability**: Context7-confirmed FastMCP prompts and resources are first-class, parameter-validated server components that are useful when you want reusable guidance in addition to tools.

## Current repository architecture analysis

### What the repo already did well

- `scholar_search_mcp/dispatch.py` already centralizes tool routing and keeps provider calls predictable.
- `scholar_search_mcp/models/tools.py` already gives the server a strong typed contract with strict input validation (`extra="forbid"`), useful aliases, and limit clamping.
- `scholar_search_mcp/models/common.py` already normalizes provider payloads into stable `Paper`, `Author`, pagination, and response models.
- `scholar_search_mcp/search.py` already contains a sensible broker/fallback chain and correctly avoids returning unfiltered CORE/SerpApi results when Semantic Scholar-only filters are requested.
- The provider split under `scholar_search_mcp/clients/` is good and worth preserving.
- Tests in `tests/test_server.py` already cover a large amount of dispatch, pagination, and provider-normalization behavior.

### Where the old design created agent friction

- `scholar_search_mcp/server.py` previously wrapped every tool result in `TextContent(text=json.dumps(...))`. That forced agents to parse JSON from text instead of receiving structured content.
- `search_papers` hid too much routing behavior. Agents could see `providerUsed`, but they could not see which providers were skipped, failed, or bypassed due to filter compatibility.
- Offset-backed tool argument descriptions in `scholar_search_mcp/models/tools.py` still described cursors as stringified offsets even though the server had already moved to opaque server-issued cursors.
- The server surface only exposed tools. There was no first-class workflow guide or reusable planning prompt to help agents choose between `search_papers`, `search_papers_bulk`, citation expansion, or author expansion.
- Runtime startup in `scholar_search_mcp/runtime.py` only supported low-level stdio boot. That was fine for local use but not ideal for a production-minded FastMCP deployment story.

## Target FastMCP architecture

### Preserved pieces

- Keep `dispatch.py` as the single execution switchboard.
- Keep `search.py` as the broker/fallback layer.
- Keep provider clients under `scholar_search_mcp/clients/`.
- Keep Pydantic response models and normalized provider payloads.
- Keep the existing compatibility helpers (`server.list_tools()` / `server.call_tool()`) so internal tests and direct module users do not break unnecessarily.

### Redesigned pieces

- Replace the low-level `mcp.server.Server(...)` bootstrap with `FastMCP(...)`.
- Register all MCP tools on the FastMCP app while still dispatching through the existing typed Pydantic models.
- Use FastMCP structured tool responses so MCP clients receive `structured_content` / `data` instead of JSON-in-text only.
- Add `TimingMiddleware` for basic observability with minimal code.
- Expose a resource (`guide://scholar-search/agent-workflows`) and prompt (`plan_scholar_search`) to reduce agent discovery friction.
- Expand `brokerMetadata` to include `attemptedProviders`, `semanticScholarOnlyFilters`, and `recommendedPaginationTool`.
- Add transport settings so the same codebase supports stdio and HTTP-oriented deployment paths.

## Migration plan in phases

### Phase 1 - framework migration

- Replace the low-level server with FastMCP.
- Keep the provider, dispatch, and model layers unchanged as much as possible.
- Preserve public tool names and input fields.
- Add in-memory FastMCP client tests to verify structured output.

### Phase 2 - agent UX improvements

- Keep `search_papers` as the quick brokered entry point.
- Make broker routing visible through `attemptedProviders`.
- Keep `pagination.nextCursor` opaque and stable, but document it honestly everywhere as opaque.
- Add prompts/resources for onboarding and workflow planning.

### Phase 3 - production deployment hardening

- Prefer `stdio` for desktop/local clients and Streamable HTTP for remote deployment.
- Add optional auth middleware or a deployment-layer auth integration before advertising public multi-tenant HTTP use.
- Validate `Origin` and front the ASGI app with standard HTTP controls when exposed remotely, consistent with the MCP transport guidance confirmed through Context7.

## Specific tool UX recommendations

### `search_papers`

- Keep the name. It is descriptive and already agent-friendly.
- Keep it explicitly **single-page brokered search**.
- Always return `brokerMetadata`.
- Include `attemptedProviders` so an agent can understand whether it should retry differently, switch tools, or explain a partial result to the user.

### `search_papers_bulk`

- Keep it as the explicit paginated retrieval tool.
- Continue treating `cursor` as an opaque token.
- Continue exposing `pagination.hasMore` and `pagination.nextCursor`.
- Keep this as the recommended path for exhaustive retrieval.

### Offset-backed pagination tools

- Keep the single `cursor` input across paginated tools.
- Do not tell agents the cursor is an integer offset if the server now wraps it as an opaque structured token.
- Preserve the current cursor safety checks that prevent cross-tool and cross-query misuse.

### Error behavior

- Keep strict input validation.
- Continue returning actionable cursor errors.
- If future work expands this migration, convert broker/runtime errors into explicitly typed tool errors so agents can branch on machine-readable error codes instead of message parsing.

## Risks, tradeoffs, and compatibility notes

- **Compatibility win**: public tool names and most result shapes remain stable.
- **Compatibility tradeoff**: tool listings from FastMCP now include richer metadata such as annotations and titles. This is beneficial for clients but may slightly change raw introspection output.
- **Structured output win**: agents no longer need to parse JSON blobs when interacting through a FastMCP client.
- **Remaining risk**: remote HTTP deployment is now architecturally supported, but auth/origin policy still needs deployment-specific hardening before recommending broad internet exposure.
- **Testing tradeoff**: the repo still keeps compatibility wrappers for legacy tests; that is intentional to minimize churn while the FastMCP surface becomes the real runtime path.

## Concrete implementation guidance

### Suggested module shape

- `scholar_search_mcp/server.py`
  - FastMCP app construction
  - dynamic tool registration
  - onboarding resource/prompt
  - compatibility helpers
- `scholar_search_mcp/runtime.py`
  - transport-aware `run_server(...)`
- `scholar_search_mcp/settings.py`
  - provider settings plus transport settings
- `scholar_search_mcp/dispatch.py`
  - typed execution router
- `scholar_search_mcp/search.py`
  - broker/fallback policy and broker metadata shaping

### Representative FastMCP pattern

```python
app = FastMCP(
    "scholar-search",
    instructions=SERVER_INSTRUCTIONS,
    strict_input_validation=True,
)
app.add_middleware(TimingMiddleware(logger=logger))

@app.resource("guide://scholar-search/agent-workflows")
def agent_workflows() -> str:
    return AGENT_WORKFLOW_GUIDE

@app.prompt(name="plan_scholar_search")
def plan_scholar_search(topic: str) -> str:
    return f"Start with search_papers for {topic}, then paginate with search_papers_bulk if needed."
```

### Why this is better for agents

- Tools remain stable and action-oriented.
- Structured outputs reduce retries caused by parsing failures.
- The workflow guide and planning prompt reduce discovery friction.
- Explicit broker attempt metadata reduces ambiguity and lets agents explain fallback behavior accurately.

## Testing recommendations

- Keep the existing provider/dispatch unit tests.
- Add FastMCP in-memory client tests for:
  - structured tool results
  - tool annotations and schema discoverability
  - resources and prompts
  - transport-related settings parsing
- Continue running `pytest`, `mypy`, `bandit`, and `pre-commit run --all-files`.
- If HTTP deployment becomes a first-class supported mode, add ASGI-level tests around `http_app`.

## Ideal target shape

An ideal near-term shape for this repository is:

- FastMCP app as the canonical runtime surface
- strict, typed tool inputs
- structured outputs for every tool
- explicit broker routing metadata
- opaque and consistently documented cursor semantics
- a lightweight resource/prompt onboarding layer
- stdio-first local usage with a clean path to authenticated remote HTTP deployment
