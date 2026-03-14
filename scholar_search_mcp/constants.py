"""Shared constants for the Scholar Search MCP package."""

API_BASE_URL = "https://api.semanticscholar.org/graph/v1"
RECOMMENDATIONS_BASE_URL = "https://api.semanticscholar.org/recommendations/v1"
CORE_API_BASE = "https://api.core.ac.uk/v3/search/works"
ARXIV_API_BASE = "https://export.arxiv.org/api/query"

MAX_429_RETRIES = 6

# Semantic Scholar enforces 1 request per second across all endpoints for
# API-key holders.  The extra 0.05 s is a safety margin so the client stays
# comfortably below the published ceiling even under slight clock jitter.
SEMANTIC_SCHOLAR_MIN_INTERVAL = 1.05  # 1.0 s hard limit + 0.05 s safety margin

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"

DEFAULT_PAPER_FIELDS = [
    "paperId",
    "title",
    "abstract",
    "year",
    "authors",
    "citationCount",
    "referenceCount",
    "influentialCitationCount",
    "venue",
    "publicationTypes",
    "publicationDate",
    "url",
]

DEFAULT_AUTHOR_FIELDS = [
    "authorId",
    "name",
    "affiliations",
    "homepage",
    "paperCount",
    "citationCount",
    "hIndex",
]
