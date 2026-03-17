# Scholar Search Golden Paths

This document captures the primary planning assumptions for the MCP surface so
agents can choose the next tool with low context and high reliability.

These same discovery, pagination, lookup, citation, and author-pivot paths are
exercised by the agentic smoke test in `.github/workflows/test-scholar-search.md`.

## Primary Personas

- **Quick discovery user**: wants a strong first page fast to decide whether to
  dig deeper.
- **Researcher doing exhaustive retrieval**: wants many papers across pages to
  build a reading list or dataset.
- **Citation chaser**: starts from one paper and expands outward through cited-by
  and reference relationships.
- **Known-item lookup user**: has a messy title, DOI, arXiv ID, URL, or partial
  clue and wants the right paper quickly.
- **Author-centric user**: wants to understand an author's work, recent output,
  or collaborators.

## Golden Paths

### 1. Quick literature discovery

1. Start with `search_papers`.
2. Read `brokerMetadata.nextStepHint` for the recommended next move.
3. Inspect `brokerMetadata.providerUsed` and `brokerMetadata.attemptedProviders`.
4. Decide whether to broaden, narrow, paginate with `search_papers_bulk`, or
   pivot into citations/authors.

**Example request**: "Find recent papers on large language model alignment"

**Tool sequence**:
```
search_papers(query="large language model alignment", limit=10)
→ read brokerMetadata.nextStepHint
→ if more needed: search_papers_bulk(query="...", limit=100)
→ for interesting paper X: get_paper_citations(paper_id=X.paperId)
```

**Success signals**

- `brokerMetadata.nextStepHint` is readable and tells the agent what to do next.
- The first response clearly explains where the results came from.
- The agent can explain whether to broaden, narrow, paginate, or pivot.

### 2. Exhaustive retrieval

1. Start with `search_papers_bulk` when the request asks for all results, the
   first N results across pages, or a dataset-like collection.
2. Treat `pagination.nextCursor` as opaque and pass it back as `cursor`
   unchanged.
3. Continue until `pagination.hasMore` is false.
4. For small targeted pages, prefer `search_papers` or
   `search_papers_semantic_scholar`; the upstream bulk endpoint may ignore small
   `limit` values internally, and this server only truncates the returned data.

**Example request**: "Get me all papers on RLHF published since 2020"

**Tool sequence**:
```
search_papers_bulk(query="reinforcement learning from human feedback", year="2020-", limit=100)
→ while pagination.hasMore:
    search_papers_bulk(query="...", year="2020-", cursor=pagination.nextCursor, limit=100)
```

**Success signals**

- Cursor handling stays explicit and safe.
- The agent does not misuse single-page tools for bulk collection.
- The agent does not misuse bulk search for small targeted pages.
- Pagination state is explained in user-facing language.

### 3. Citation chasing

1. Resolve or confirm the starting paper with `search_papers_match` or
   `get_paper_details` if needed.
2. Use `get_paper_citations` for cited-by expansion.
3. Use `get_paper_references` for backward references.
4. Use `get_paper_authors` if the next step is an author or collaborator pivot.

If the starting paper came from brokered non-Semantic-Scholar results, prefer
`paper.recommendedExpansionId` when it is present. If
`paper.expansionIdStatus` is `not_portable`, do not reuse brokered `paperId`,
`sourceId`, or `canonicalId` directly in Semantic Scholar expansion tools;
resolve the paper through DOI or a Semantic Scholar-native lookup first.

**Example request**: "What papers cite 'Attention Is All You Need'?"

**Tool sequence**:
```
search_papers_match(query="Attention Is All You Need")
→ get_paper_citations(paper_id=result.paperId, limit=100)
→ while pagination.hasMore:
    get_paper_citations(paper_id=result.paperId, cursor=pagination.nextCursor)
```

**Success signals**

- The agent explains the direction clearly: cited by vs references.
- Returned metadata is rich enough to rank or filter the expansion set.
- The workflow naturally chains from a discovered or known paper.

### 4. Known-item lookup

1. Use `search_papers_match` for messy or partial titles.
2. Use `get_paper_details` for DOI, arXiv ID, URL, or canonical IDs.
3. Fall back to `search_papers` only when the user is really asking a topical
   question rather than an item lookup.
4. Treat a structured no-match from `search_papers_match` as a signal that the
   item may be punctuation-variant metadata, a dissertation, software release,
   report, or other output outside the indexed paper surface. Verify externally
   when needed.

**Example requests and tool choices**:
- "Find the paper called something like 'Scaling Laws for Neural Language Models'"
  → `search_papers_match(query="Scaling Laws for Neural Language Models")`
- "Get details for arxiv:1706.03762"
  → `get_paper_details(paper_id="arXiv:1706.03762")`
- "Look up DOI 10.48550/arXiv.2005.14165"
  → `get_paper_details(paper_id="DOI:10.48550/arXiv.2005.14165")`

**Success signals**

- Disambiguation stays minimal.
- DOI, URL, and identifier-based lookups feel low friction.
- Agents do not spend multiple topic-search turns on a known-item request.

### 5. Author-centric research

1. Start with `search_authors`.
2. Use `get_author_info` to confirm identity and profile metadata.
3. Use `get_author_papers` to expand into the author's work.
4. Use `get_paper_authors` when the user starts from a paper instead of a name.
5. When the starting paper came from brokered non-Semantic-Scholar results,
   prefer `paper.recommendedExpansionId` for the `paper_id` you pass into
   Semantic Scholar expansion tools. If `paper.expansionIdStatus` is
   `not_portable`, do not reuse brokered `paperId`/`sourceId`/`canonicalId`
   values directly; resolve the paper through DOI or a Semantic Scholar-native
   lookup first.
6. For common names, add affiliation, coauthor, venue, or topic clues in the
   initial `search_authors` query, then use profile metadata to confirm the
   right person before reading papers.

**Example request**: "What has Yoshua Bengio published recently?"

**Tool sequence**:
```
search_authors(query="Yoshua Bengio", limit=5)
→ get_author_info(author_id=top_match.authorId)
→ get_author_papers(author_id=top_match.authorId, publicationDateOrYear="2022-", limit=50)
```

**Success signals**

- Author search feels first-class instead of secondary.
- Agents can pivot cleanly between paper and author workflows.
- Agents use Semantic Scholar-compatible paper/author identifiers when pivoting
  out of brokered results.
- Recent work and collaborator exploration are easy next steps.

## Secondary Workflows

- **Quote or snippet validation**: use `search_snippets` only when title or
  keyword search is weak.
- **Agent UX feedback loop**: the checked-in agentic workflow at
  `.github/workflows/test-scholar-search.md` now supports `smoke`,
  `comprehensive`, and `feature_probe` review modes. The workflow runs GPT-5.4
  and explicitly evaluates agent UX in every step: intuitiveness, unnecessary
  round trips, missing features, confusing contracts, and dead-end responses.
  Each run produces a structured UX friction summary before filing any issue.
  Start with the smoke baseline, then add deeper probes or a feature-specific
  focus prompt when you need broader UX feedback. Issues created by the
  verifier carry `agentic` and `needs-copilot` labels with stable body markers.
  The auto-assignment workflow listens to both issue events and completed
  verifier runs so workflow-created issues still get assigned to GitHub Copilot
  without duplicates.
  After 3 failed fix attempts the issue escalates to `needs-human`.
- **Explicit OpenAlex workflows**: use `search_papers_openalex` for one
  OpenAlex page, `search_papers_openalex_bulk` for OpenAlex cursor traversal,
  `get_paper_details_openalex` for OpenAlex W-id/DOI lookup, and the OpenAlex
  citation/author tools when the task explicitly needs OpenAlex-native DOI/ID,
  author, or paging semantics instead of the default broker.
- **Citation export**: use `get_paper_citation_formats` after SerpApi discovery
  when a result exposes `paper.scholarResultId` (a first-class field, `None`
  for non-SerpApi results). Pass `result_id=paper.scholarResultId`, not
  `paper.sourceId`.
- **Budget-aware searching**: steer `search_papers` with `preferredProvider` or
  `providerOrder` before falling back to provider-specific tools.

## Recent UX Fixes

These rough edges from the prior UX review are now fixed and should be treated
as part of the intended agent contract.

### 1. `search_papers_match` now resolves to one paper payload

- The Semantic Scholar match path now normalizes wrapped responses to a single
  paper-shaped object.
- Agents should no longer need to defensively inspect `data[0]` for the best
  match.
- Exact-match 400/404 misses now fall back to fuzzy Semantic Scholar title
  search, and exhausted match attempts return a structured no-match payload
  instead of surfacing a raw provider 404.

### 2. Default CORE first hop follows redirects

- The default broker path now follows predictable CORE redirects instead of
  recording an avoidable first-provider failure.
- Treat new redirect-driven fallback in `brokerMetadata.attemptedProviders` as a
  regression if it reappears.

### 3. `nextStepHint` now distinguishes continuation from pivots

- Semantic Scholar results describe `search_papers_bulk` as the closest
  continuation path only when that preserves the research intent reasonably
  well.
- CORE, arXiv, and SerpApi results now describe `search_papers_bulk` as a
  Semantic Scholar pivot rather than another page from the same provider.
- Venue-filtered Semantic Scholar searches explicitly warn that bulk retrieval
  broadens the query semantics.

### 4. Provider-specific schemas now match provider capability

- `search_papers_core`, `search_papers_serpapi`, and `search_papers_arxiv`
   expose only `query`, `limit`, and `year`.
- `search_papers_openalex` also keeps its single-page contract explicit with
  only `query`, `limit`, and `year`, while `search_papers_openalex_bulk`
  exposes OpenAlex cursor pagination as a separate tool.
- `search_papers_semantic_scholar` continues to expose the wider Semantic
   Scholar-compatible filter set.

### 5. Author and paper pivots now call out Semantic Scholar ID boundaries

- `search_authors` normalizes plain-text exact-name punctuation before calling
  Semantic Scholar.
- Common-name author workflows now explicitly recommend affiliation, coauthor,
  venue, and topic clues before profile confirmation.
- Author-profile tools now describe the supported author fields explicitly.
- Semantic Scholar paper-expansion tools now tell agents to prefer
  `paper.recommendedExpansionId` when present, and to treat
  `paper.expansionIdStatus='not_portable'` as a signal that brokered
  `paperId`/`sourceId`/`canonicalId` values still need a DOI or
  Semantic-Scholar-native lookup before expansion.

### 6. Snippet-search provider failures now degrade cleanly

- `search_snippets` now returns an empty degraded payload with retry guidance
  when Semantic Scholar rejects a phrase query or returns a transient 5xx.
- Agents should prefer `search_papers_match` or `search_papers` before falling
  back to snippet search for quote recovery.

## Future Work

- Consider per-request or per-session provider preferences for budget-aware use.
- Decide whether retry-recovered provider behavior should remain internal or be
  surfaced to agents as part of the broker story.
- Consider whether the agentic workflow should eventually split into multiple
  checked-in workflows once the new manual mode/focus inputs settle and more
  specialized UX probes become routine.
