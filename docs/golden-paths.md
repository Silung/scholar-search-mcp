# Scholar Search Golden Paths

This document captures the primary planning assumptions for the MCP surface so
agents can choose the next tool with low context and high reliability.

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
2. Inspect `brokerMetadata.providerUsed` and
   `brokerMetadata.attemptedProviders`.
3. Decide whether to broaden, narrow, paginate with `search_papers_bulk`, or
   pivot into citations/authors.

**Success signals**

- The first response clearly explains where the results came from.
- The response gives enough metadata to choose the next move without retrying.
- The agent can explain whether to broaden, narrow, paginate, or pivot.

### 2. Exhaustive retrieval

1. Start with `search_papers_bulk` when the request asks for all results, the
   first N results across pages, or a dataset-like collection.
2. Treat `pagination.nextCursor` as opaque and pass it back as `cursor`
   unchanged.
3. Continue until `pagination.hasMore` is false.

**Success signals**

- Cursor handling stays explicit and safe.
- The agent does not misuse single-page tools for bulk collection.
- Pagination state is explained in user-facing language.

### 3. Citation chasing

1. Resolve or confirm the starting paper with `search_papers_match` or
   `get_paper_details` if needed.
2. Use `get_paper_citations` for cited-by expansion.
3. Use `get_paper_references` for backward references.
4. Use `get_paper_authors` if the next step is an author or collaborator pivot.

**Success signals**

- The agent explains the direction clearly: cited by vs references.
- Returned metadata is rich enough to rank or filter the expansion set.
- The workflow naturally chains from a discovered or known paper.

### 4. Known-item lookup

1. Use `search_papers_match` for messy or partial titles.
2. Use `get_paper_details` for DOI, arXiv ID, URL, or canonical IDs.
3. Fall back to `search_papers` only when the user is really asking a topical
   question rather than an item lookup.

**Success signals**

- Disambiguation stays minimal.
- DOI, URL, and identifier-based lookups feel low friction.
- Agents do not spend multiple topic-search turns on a known-item request.

### 5. Author-centric research

1. Start with `search_authors`.
2. Use `get_author_info` to confirm identity and profile metadata.
3. Use `get_author_papers` to expand into the author’s work.
4. Use `get_paper_authors` when the user starts from a paper instead of a name.

**Success signals**

- Author search feels first-class instead of secondary.
- Agents can pivot cleanly between paper and author workflows.
- Recent work and collaborator exploration are easy next steps.

## Secondary Workflows

- **Quote or snippet validation**: use `search_snippets` only when title or
  keyword search is weak.
- **Citation export**: use `get_paper_citation_formats` after discovery when a
  SerpApi Google Scholar result exposes `paper.scholarResultId`.
- **Budget-aware searching**: steer `search_papers` with `preferredProvider` or
  `providerOrder` before falling back to provider-specific tools.

## Future Work

- Add workflow-specific examples to the MCP resource and README for each golden
  path.
- Consider per-request or per-session provider preferences for budget-aware use.
- Add success-metric tests that assert workflow cues stay visible in tool
  descriptions and onboarding resources.
