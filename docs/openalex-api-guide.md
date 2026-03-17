# OpenAlex API Guide

This guide describes how to use the OpenAlex API effectively when evaluating it
as a future provider for this MCP server.

It focuses on the parts that matter most for integration work in this repo:

- `/works` as the main paper-search and paper-detail surface
- authentication, rate limits, and polite-pool etiquette
- pagination and batching for large result sets
- search and filter semantics that differ from the existing providers here
- provider-specific payload nuances that affect normalization into MCP-friendly
  paper, citation, and author flows

Primary references:

- Overview: https://developers.openalex.org/
- API overview: https://developers.openalex.org/api-reference/introduction
- Rate limits and authentication: https://developers.openalex.org/guides/authentication
- Paging: https://developers.openalex.org/guides/page-through-results
- Works overview: https://developers.openalex.org/api-reference/works
- Search entities: https://developers.openalex.org/guides/searching

## Operating Principles

If you remember only a few things, make them these:

1. OpenAlex is open by default, but production integrations should still send a
   contact email for the polite pool.
2. Treat the API as credit-limited, not merely request-limited.
3. Use list endpoints carefully: they cost more than singleton lookups.
4. Prefer `select` plus targeted filters over fetching full work payloads you do
   not need.
5. For large traversals, use cursor paging and treat `meta.next_cursor` as
   opaque.
6. Search by related-entity IDs, not by free-text author or institution names.

## Authentication and Identification

OpenAlex does **not** require an API key for standard use. For most exploratory
or low-volume MCP use, requests can be made anonymously.

However, two integration details still matter:

- Add `mailto=you@example.com` to requests, or include
  `mailto:you@example.com` in the `User-Agent`, to join the **polite pool**.
- Premium users can send `api_key=...` to unlock higher limits and certain
  premium-only filters such as `from_updated_date`.

Example:

```text
https://api.openalex.org/works?search=transformer&mailto=team@example.com
https://api.openalex.org/works?filter=doi:https://doi.org/10.48550/arXiv.1706.03762&api_key=YOUR_KEY
```

The current official docs describe the polite pool mainly as a response-time
and reliability improvement, not as a separate excuse to ignore the published
rate limits. A future client for this repo should still enforce its own pacing.

## Rate Limits and Credit Costs

OpenAlex currently documents a credit-based model:

| Endpoint type | Example | Credit cost |
| --- | --- | --- |
| Singleton | `/works/W2741809807` | 1 |
| List | `/works?search=rlhf` | 10 |
| Content | future PDF/content endpoints | 100 |
| Vector | future vector endpoints | 1,000 |
| Text | `/text/topics?...` | 1,000 |

Published limits:

- **100,000 credits/day** for free users
- **100 requests/second** overall

This matters for MCP design because OpenAlex list traffic is relatively
expensive compared with singleton lookups. A provider implementation should:

- avoid doing broad list queries inside tight retry loops
- reuse results instead of immediately refetching adjacent pages
- prefer singleton follow-ups only for items the user actually needs expanded
- expose limits clearly in any future provider-specific tool descriptions

Every response also includes rate-limit headers such as
`X-RateLimit-Remaining`, and the `/rate-limit` endpoint can be queried when an
API key is available.

## Base Surface Most Relevant to This Repo

OpenAlex is much broader than this server needs, but a future provider
integration would mostly care about the following:

| MCP capability | Best OpenAlex surface | Notes |
| --- | --- | --- |
| quick paper discovery | `GET /works?search=...` | good default topical search |
| paper details | `GET /works/{id}` | supports OpenAlex IDs and DOI-style lookups |
| exact-ish title lookup | `GET /works?filter=title.search:...` | no dedicated best-match endpoint like Semantic Scholar |
| autocomplete | `GET /autocomplete/works?q=...` | returns lightweight title/hint results, not full work objects |
| references | `referenced_works` on a work | follow with batched work-ID lookup on `/works` rather than one request per reference |
| citations | `cited_by_api_url` on a work | OpenAlex exposes an API URL for incoming citations |
| author pivot | `authorships.author.id`, `/authors`, `/works?filter=authorships.author.id:...` | typically a two-step flow |
| venue/source pivot | `primary_location.source.id` | source IDs are more reliable than searching by venue name |

In this repo specifically, OpenAlex would fit best as a metadata-rich search and
lookup provider. It is less of a drop-in replacement for the current Semantic
Scholar expansion flow because several semantics are different:

- there is no direct equivalent of Semantic Scholar's `/paper/search/match`
- incoming citations are exposed through `cited_by_api_url` rather than a
  dedicated sibling endpoint contract like this repo already uses
- abstracts are not returned as plain text

## Works Endpoint Behavior

`/works` is the main entity family for paper-like records.

Common shapes:

```text
GET https://api.openalex.org/works
GET https://api.openalex.org/works?search=diffusion models
GET https://api.openalex.org/works/W2741809807
GET https://api.openalex.org/works?filter=doi:https://doi.org/10.48550/arXiv.1706.03762
```

Important response-shape details for normalization:

- list endpoints return `{ "meta": ..., "results": [...] }`
- single-entity endpoints return the work object directly
- the top-level work identifier is a full URI such as
  `https://openalex.org/W2741809807`
- DOI values are URI-formatted as well, e.g. `https://doi.org/...`

That means a future client for this repo should normalize IDs deliberately
instead of assuming short provider-native strings like the current Semantic
Scholar or CORE flows.

## Search Semantics

OpenAlex supports two broad search modes for works:

1. `search=...` for general title/abstract/fulltext search
2. fielded search filters such as `filter=title.search:...`

Important search behavior:

- `search` on works covers title, abstract, and some full text
- boolean operators `AND`, `OR`, and `NOT` are supported when uppercase
- quotes and parentheses are supported
- stemming and stop-word removal are enabled by default
- `*.search.no_stem` filters disable stemming for title/abstract-style search
- wildcard and fuzzy characters like `*`, `?`, and `~` are not allowed in
  boolean search; they are removed

Examples:

```text
/works?search=(alignment AND "large language model") NOT benchmark
/works?filter=title.search:transformer
/works?filter=title.search.no_stem:surgery
```

For this MCP server, that means OpenAlex search would sit somewhere between:

- broker-style quick topical discovery, and
- a fielded lookup provider for titles, sources, institutions, and topics

But it would not map perfectly onto the current Semantic Scholar-only filters.
Any future `search_papers_openalex` tool should advertise only the parameters
that OpenAlex actually honors.

## Filter Semantics That Matter for MCP Integration

OpenAlex filters are powerful, but they have rules that differ from the current
providers in this repo.

### AND, OR, NOT

- filters are ANDed by default:
  `filter=publication_year:2024,is_oa:true`
- OR within a single filter uses `|`
- negation uses `!`
- AND within a single repeated attribute can use `+` or repeated filters

Examples:

```text
filter=type:article|book
filter=country_code:!us
filter=institutions.country_code:fr+gb
filter=cited_by_count:>100,is_oa:true
```

Important nuance: OR works **within one filter key**, not across different
filter attributes. If a future tool exposes high-level filter composition, it
should not pretend that OpenAlex can express arbitrary boolean combinations
across unrelated fields in one request.

### Batch-by-OR instead of N singleton calls

OpenAlex supports up to **100 values** in one OR filter. This is especially
useful for DOI or ID batch lookup:

```text
/works?filter=doi:https://doi.org/10.1/abc|https://doi.org/10.2/def&per-page=100
```

For a future MCP provider, this is likely the right building block for:

- batched known-item DOI resolution
- hydrating `referenced_works` after reading a single work
- reducing credit usage compared with dozens of singleton GETs

## Pagination

OpenAlex supports both page-based and cursor-based pagination.

### Basic paging

- request with `page=N`
- request size is controlled with `per-page=1..200`
- only works for the first 10,000 results

### Cursor paging

- start with `cursor=*`
- read `meta.next_cursor`
- pass it back unchanged as `cursor=<token>`
- continue until `meta.next_cursor` is `null`

Examples:

```text
/works?filter=publication_year:2023&per-page=200&page=2
/works?filter=publication_year:2023&per-page=200&cursor=*
```

Provider-specific nuance:

- the request parameter is spelled `per-page` in the docs
- the response metadata field is spelled `per_page`
- `next_cursor` is provider-issued and should be treated as opaque

If OpenAlex is ever wired into this MCP server, we should keep the server-side
cursor contract opaque just as we do today for Semantic Scholar-backed
pagination rather than leaking raw provider pagination assumptions into the MCP
surface.

Also note the OpenAlex docs explicitly discourage using cursor pagination to
download the full dataset; for corpus-scale ingestion, the snapshot is the
correct path.

## Data-Model Nuances Relevant to Normalization

Several OpenAlex work fields are especially important when mapping into this
repo's normalized paper shape.

### 1. Abstracts are not plain text

OpenAlex exposes `abstract_inverted_index`, not a plain `abstract` string.

The safest default for this repo would be:

- reconstruct plaintext abstracts client-side for detail-style responses
- omit the abstract field for search/list responses when reconstruction is not
  worth the cost
- never return a misleading partial abstract if reconstruction fails

This is one of the biggest differences from Semantic Scholar and CORE.

### 2. Citations and references use different primitives

- outgoing references are given as `referenced_works`
- incoming citations are accessed through `cited_by_api_url`
- related-paper style exploration is available through `related_works`

This makes OpenAlex viable for citation chasing, but the implementation shape is
different from the existing Semantic Scholar citation/reference endpoints.

### 3. Authorship payloads are capped

`authorships` are limited to the first 100 authors. A future normalization layer
should not silently imply that the author list is always exhaustive; if a work
reaches that cap, treat the author list as potentially partial in downstream MCP
responses and documentation.

### 4. Venue/location fields have migrated

The docs explicitly deprecate `host_venue` and `alternate_host_venues` in favor
of `primary_location` and `locations`.

So any new provider code should avoid building on deprecated venue fields.

### 5. Source aggregation affects deduplication

OpenAlex aggregates records from multiple upstream sources, including Crossref,
PubMed, repositories, and arXiv. In this repo that matters because a future
brokered path would overlap heavily with existing CORE, arXiv, and Semantic
Scholar coverage.

Practical implication: dedupe on stable identifiers like DOI and carefully
normalized titles, not just provider-native IDs.

## Two-Step Related-Entity Lookup

One of the most important OpenAlex patterns is: **search entity, then filter
works by ID**.

Examples:

```text
/authors?search=Yoshua Bengio
/works?filter=authorships.author.id:A5001980242

/institutions?search=MIT
/works?filter=authorships.institutions.id:I136199984

/sources?search=Nature
/works?filter=primary_location.source.id:S137773608
```

This is a good fit for explicit multi-step MCP workflows, but a poor fit for a
single over-broad search tool that pretends free-text related-entity search is
precise. If this repo ever adds OpenAlex provider-specific tools, author,
institution, and source pivots should stay honest about that two-step pattern.

## `select` for Smaller Payloads

OpenAlex supports `select=field1,field2,...`, but only for **root-level**
fields.

Example:

```text
/works?select=id,doi,display_name,publication_year,cited_by_count
```

This is useful for fast list views and broker-style search results. However, it
cannot select nested fields such as `open_access.is_oa`. A future provider
client should therefore maintain a few known-good field sets rather than trying
to build arbitrarily deep response masks.

## Where OpenAlex Would Likely Fit in This MCP Server

If the repo adds OpenAlex later, the cleanest positioning would likely be:

- **search/discovery**: a free, broad metadata provider with rich filters
- **known-item DOI/title recovery**: especially useful when users have DOI,
  OpenAlex ID, or related-entity constraints
- **citation/reference pivots**: feasible, but with OpenAlex-specific mechanics
- **author/institution/source pivots**: strong, provided the tool flow stays
  explicitly two-step

Less likely clean fits:

- a direct replacement for Semantic Scholar's best-match tool
- a drop-in citation expansion backend without translation work
- any contract that assumes plain-text abstracts are always available

## Recommended Integration Defaults

If implementing a future OpenAlex client in this repo, start with these
defaults:

1. Always send a configured contact email when available.
2. Keep a shared limiter even though OpenAlex's published ceiling is much higher
   than Semantic Scholar's.
3. Normalize `https://openalex.org/W...` and DOI URLs carefully before storing
   IDs in MCP payloads.
4. Use `select` for list/search responses and fetch fuller payloads only for
   details.
5. Use cursor pagination for exhaustive retrieval, but keep the MCP cursor
   opaque and server-issued.
6. Prefer batched OR filters for DOI or reference hydration instead of loops of
   singleton requests.
7. Avoid exposing deprecated venue fields or unsupported cross-field boolean
   semantics in any future tool schema.

## Bottom Line

OpenAlex looks promising as a future provider for this repo because it is open,
metadata-rich, and strong at ID-based filtering and entity pivots.

The main integration traps are not authentication but **semantic mismatch**:

- credit-based list costs
- URI-shaped identifiers
- abstract reconstruction
- two-step related-entity workflows
- citation and paging mechanics that differ from Semantic Scholar

If we add it later, the best result will come from a provider-specific MCP
surface that is explicit about those differences rather than trying to squeeze
OpenAlex into an existing provider contract it does not quite match.
