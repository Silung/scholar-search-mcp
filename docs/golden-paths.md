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
- Pagination state is explained in user-facing language.

### 3. Citation chasing

1. Resolve or confirm the starting paper with `search_papers_match` or
   `get_paper_details` if needed.
2. Use `get_paper_citations` for cited-by expansion.
3. Use `get_paper_references` for backward references.
4. Use `get_paper_authors` if the next step is an author or collaborator pivot.

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
- Recent work and collaborator exploration are easy next steps.

## Secondary Workflows

- **Quote or snippet validation**: use `search_snippets` only when title or
  keyword search is weak.
- **Citation export**: use `get_paper_citation_formats` after SerpApi discovery
  when a result exposes `paper.scholarResultId` (a first-class field, `None`
  for non-SerpApi results). Pass `result_id=paper.scholarResultId`, not
  `paper.sourceId`.
- **Budget-aware searching**: steer `search_papers` with `preferredProvider` or
  `providerOrder` before falling back to provider-specific tools.

## Future Work

- Consider per-request or per-session provider preferences for budget-aware use.
- Add success-metric tests that assert workflow cues stay visible in tool
  descriptions and onboarding resources.
