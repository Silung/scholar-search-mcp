---
description: |
  Exercise the primary Scholar Search MCP golden paths with an agent so the
  repo gets a scheduled, high-level regression check of discovery,
  pagination, author pivot, and optional citation-export workflows.

on:
  workflow_dispatch:
  schedule: weekly on sunday

permissions: read-all

network: defaults

engine: copilot

timeout-minutes: 20

safe-outputs:
  create-issue:
    title-prefix: "[agentic-test] "
    labels: [automation, testing]
    max: 1

tools:
  github:
    toolsets: [issues]
  bash: true

mcp-servers:
  scholar-search:
    command: bash
    args:
      - -lc
      - pip install -e .[dev] >/tmp/scholar-search-agentic-install.log && python -m scholar_search_mcp
    env:
      CORE_API_KEY: "${{ secrets.CORE_API_KEY }}"
      SEMANTIC_SCHOLAR_API_KEY: "${{ secrets.SEMANTIC_SCHOLAR_API_KEY }}"
    allowed:
      - search_papers
      - search_papers_bulk
      - search_papers_core
      - search_papers_semantic_scholar
      - search_papers_serpapi
      - search_papers_arxiv
      - search_papers_match
      - get_paper_details
      - get_paper_citations
      - get_paper_references
      - search_authors
      - get_author_info
      - get_author_papers
      - get_paper_citation_formats
---

# Test Scholar Search MCP

You are validating the `scholar-search-mcp` server as an end-to-end user would.
Use the MCP tools first; use bash only when you need short local validation or to
inspect structured output more carefully.

This workflow is a smoke test for the primary user journeys, not a complete test
of every MCP tool. Focus on the core paths that should stay reliable for agents:
quick discovery, known-item lookup, pagination, citation chasing, author pivot,
and optional citation export when SerpApi is available.

## Goals

1. Confirm the quick-discovery path returns structured, useful metadata.
2. Confirm the exhaustive-retrieval path handles cursor pagination safely.
3. Confirm known-item lookup and citation chasing still work from the same MCP
   surface agents use in production.
4. Confirm the author-pivot path works from the same MCP surface agents use in
  production.
5. Confirm optional citation export still works when SerpApi is available.
6. Capture UX feedback about missing fields, confusing metadata, or no-result
   behavior.

## Test protocol

1. **Quick discovery**
   - Call `search_papers(query="graph neural networks", limit=5)`.
   - Record `brokerMetadata.providerUsed`, `brokerMetadata.nextStepHint`, and the
     titles/providers of the first few results.
   - Verify every returned paper has a `title` and at least one author entry.

2. **Known-item lookup**
   - Call `search_papers_match(query="Attention Is All You Need")`.
   - Use the returned identifier with `get_paper_details`.
   - Confirm the detailed record includes a stable identifier, title, and author
     metadata.

3. **Exhaustive retrieval / pagination**
   - Call `search_papers_bulk(query="graph neural networks", limit=5)`.
   - If `pagination.nextCursor` is present, call `search_papers_bulk` again with
     the exact `cursor` value that was returned.
   - Confirm there are no duplicate `paperId` values across the first two pages.
   - If no second page is available, note that result instead of forcing a
     failure.

4. **Provider-specific spot checks**
   - Run `search_papers_core(query="transformer architecture", limit=3)`.
   - Run `search_papers_semantic_scholar(query="transformer architecture", limit=3)`.
   - Run `search_papers_arxiv(query="transformer architecture", limit=3)`.
   - Verify each provider returns the normalized response shape the MCP server
     promises. For arXiv, look for arXiv-native identifiers/URLs when present;
     for CORE and Semantic Scholar, note whether DOI metadata is populated.

5. **Author pivot**
   - Run `search_authors(query="Yoshua Bengio", limit=3)`.
   - Use the top author identifier with `get_author_info`.
   - Call `get_author_papers(author_id=..., publicationDateOrYear="2022-", limit=5)`.
   - Confirm the author profile is stable enough to continue from and that the
     paper list response is structured cleanly even if recent results are sparse.

6. **Optional SerpApi citation export**
   - If the SerpApi tools are configured, run
     `search_papers_serpapi(query="Attention Is All You Need", limit=3)`.
   - If a result exposes `scholarResultId`, call
     `get_paper_citation_formats(result_id=paper.scholarResultId)`.
   - Confirm the citation-export response returns at least one named format.
   - If SerpApi is unavailable, disabled, or returns no usable `scholarResultId`,
     record a clean skip instead of failing the workflow.

7. **No-results behavior**
   - Call `search_papers(query="asdkfjhasdkjfh research paper nonsense", limit=3)`.
   - Verify the server responds cleanly with an empty/low-result payload rather
     than malformed metadata or an unhelpful failure.

8. **Assessment**
   - Summarize whether the server returned consistent metadata, whether cursor
     handling felt safe and clear, whether author workflows felt first-class,
     and whether any provider-specific gaps stood out.
   - If you find a concrete defect or UX regression, create at most one GitHub
     issue with reproduction steps and clear remediation guidance.
