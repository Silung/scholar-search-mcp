"""Typed tool argument models and schema registry."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..constants import SUPPORTED_AUTHOR_FIELDS


class ToolArgsModel(BaseModel):
    """Base MCP tool input model."""

    model_config = ConfigDict(extra="forbid")


OPAQUE_CURSOR_FIELD_DESCRIPTION = (
    "Continuation cursor from a previous response's pagination.nextCursor "
    "(an opaque server-issued cursor). Pass it back exactly as returned; do "
    "not derive, edit, or fabricate it, and do not reuse it across a "
    "different tool or query flow. Omit to start from the beginning."
)

SUPPORTED_AUTHOR_FIELDS_TEXT = ", ".join(SUPPORTED_AUTHOR_FIELDS)
AUTHOR_FIELDS_DESCRIPTION = (
    "Fields to return. Supported values: " + SUPPORTED_AUTHOR_FIELDS_TEXT
)
AUTHOR_ID_DESCRIPTION = (
    "Semantic Scholar author ID from search_authors or get_paper_authors"
)
AUTHOR_SEARCH_QUERY_DESCRIPTION = (
    "Author name to search for. Plain-text only; initials and exact-name "
    "punctuation may be normalized before the upstream request."
)
SEMANTIC_SCHOLAR_EXPANSION_PAPER_ID_DESCRIPTION = (
    "Paper identifier for Semantic Scholar expansion tools. Prefer a Semantic "
    "Scholar paperId, DOI, or canonicalId; provider-specific brokered ids such "
    "as raw CORE paperId/sourceId values are not portable."
)


def _clamp_limit(value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default
    return min(max(int(value), 1), maximum)


def _validate_author_fields(fields: list[str] | None) -> list[str] | None:
    if fields is None:
        return None
    unsupported = [field for field in fields if field not in SUPPORTED_AUTHOR_FIELDS]
    if unsupported:
        raise ValueError(
            "Unsupported author fields: "
            + ", ".join(unsupported)
            + ". Supported values: "
            + SUPPORTED_AUTHOR_FIELDS_TEXT
            + "."
        )
    return fields


SearchProvider = Literal[
    "core",
    "semantic_scholar",
    "serpapi_google_scholar",
    "arxiv",
]

SEARCH_PROVIDER_ALIASES: dict[str, SearchProvider] = {
    "core": "core",
    "semantic_scholar": "semantic_scholar",
    "serpapi": "serpapi_google_scholar",
    "serpapi_google_scholar": "serpapi_google_scholar",
    "arxiv": "arxiv",
}

DEFAULT_SEARCH_PROVIDER_ORDER: tuple[SearchProvider, ...] = (
    "core",
    "semantic_scholar",
    "serpapi_google_scholar",
    "arxiv",
)


def _supported_provider_names() -> str:
    return ", ".join(SEARCH_PROVIDER_ALIASES)


def _normalize_provider_name(value: object) -> SearchProvider:
    if not isinstance(value, str):
        raise ValueError(
            "Provider names must be strings. Supported values: "
            + _supported_provider_names()
        )
    normalized = value.strip().lower()
    try:
        return SEARCH_PROVIDER_ALIASES[normalized]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported provider {value!r}. Supported values: "
            f"{_supported_provider_names()}."
        ) from exc


def _validate_provider_order(
    value: list[object] | None,
) -> list[SearchProvider] | None:
    if value is None:
        return None
    if not value:
        raise ValueError("Provider order must contain at least one provider")
    seen: set[SearchProvider] = set()
    duplicates: list[SearchProvider] = []
    normalized_providers = [_normalize_provider_name(provider) for provider in value]
    for provider in normalized_providers:
        if provider in seen:
            duplicates.append(provider)
        seen.add(provider)
    if duplicates:
        duplicate_text = ", ".join(duplicates)
        raise ValueError(f"Provider order cannot repeat providers: {duplicate_text}")
    return normalized_providers


class BasicSearchPapersArgs(ToolArgsModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, description="Max results (default 10, max 100)")
    year: str | None = Field(
        default=None,
        description="Year filter, e.g. '2020-2023' or '2023'",
    )

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 10, 100)


class SearchPapersBaseArgs(BasicSearchPapersArgs):
    fields: list[str] | None = Field(default=None, description="Fields to return")
    venue: list[str] | None = Field(
        default=None,
        description="Venue names to filter",
    )
    publication_date_or_year: str | None = Field(
        default=None,
        alias="publicationDateOrYear",
        description=(
            "Date or date-range filter, e.g. '2019-03-05', '2016:2020', '2010-'"
        ),
    )
    fields_of_study: str | None = Field(
        default=None,
        alias="fieldsOfStudy",
        description="Comma-separated fields of study filter",
    )
    publication_types: str | None = Field(
        default=None,
        alias="publicationTypes",
        description="Comma-separated publication types filter",
    )
    open_access_pdf: bool | None = Field(
        default=None,
        alias="openAccessPdf",
        description="Only return papers with a public PDF",
    )
    min_citation_count: int | None = Field(
        default=None,
        alias="minCitationCount",
        description="Minimum citation count filter",
    )

class SearchPapersArgs(SearchPapersBaseArgs):
    preferred_provider: SearchProvider | None = Field(
        default=None,
        alias="preferredProvider",
        description=(
            "Optional provider to try first before continuing the broker fallback "
            "chain. One of: core, semantic_scholar, serpapi, "
            "serpapi_google_scholar, arxiv."
        ),
    )
    provider_order: list[SearchProvider] | None = Field(
        default=None,
        alias="providerOrder",
        description=(
            "Optional ordered provider chain override for this call. Defaults to "
            "core, semantic_scholar, serpapi_google_scholar, arxiv. Omit providers "
            "to skip them for this request. `serpapi` is accepted as a shorthand "
            "for `serpapi_google_scholar`."
        ),
    )

    @field_validator("preferred_provider", mode="before")
    @classmethod
    def normalize_preferred_provider(cls, value: object) -> SearchProvider | None:
        if value is None:
            return None
        return _normalize_provider_name(value)

    @field_validator("provider_order", mode="before")
    @classmethod
    def validate_provider_order(
        cls, value: list[object] | None
    ) -> list[SearchProvider] | None:
        return _validate_provider_order(value)


class ProviderSearchPapersArgs(SearchPapersBaseArgs):
    """Shared provider-specific single-source paper search arguments."""


class MinimalProviderSearchPapersArgs(BasicSearchPapersArgs):
    """Provider-specific search args for backends that only honor query/year."""


class SemanticProviderSearchPapersArgs(SearchPapersBaseArgs):
    """Semantic Scholar single-source search arguments."""


class BulkSearchPapersArgs(ToolArgsModel):
    query: str = Field(
        description=(
            "Search query; supports boolean/fuzzy syntax: +AND, |OR, -negate, "
            '"phrases", prefix*, ~N edit-distance, (precedence)'
        )
    )
    fields: list[str] | None = Field(default=None, description="Fields to return")
    cursor: str | None = Field(
        default=None,
        description=(
            "Continuation cursor from a previous response's pagination.nextCursor "
            "(a provider-issued token for bulk search). Pass it back exactly as "
            "returned; do not derive, edit, or fabricate it, and do not reuse it "
            "across a different query flow. Omit to start a new search."
        ),
    )
    sort: str | None = Field(
        default=None,
        description=(
            "Sort order, e.g. 'paperId', 'citationCount', 'publicationDate'"
        ),
    )
    year: str | None = Field(
        default=None,
        description="Year filter, e.g. '2020-2023' or '2023'",
    )
    publication_date_or_year: str | None = Field(
        default=None,
        alias="publicationDateOrYear",
        description="Date or date-range filter",
    )
    fields_of_study: str | None = Field(
        default=None,
        alias="fieldsOfStudy",
        description="Comma-separated fields of study filter",
    )
    publication_types: str | None = Field(
        default=None,
        alias="publicationTypes",
        description="Comma-separated publication types filter",
    )
    open_access_pdf: bool | None = Field(
        default=None,
        alias="openAccessPdf",
        description="Only return papers with a public PDF",
    )
    min_citation_count: int | None = Field(
        default=None,
        alias="minCitationCount",
        description="Minimum citation count filter",
    )
    limit: int = Field(
        default=100,
        description=(
            "Max papers returned per call (default 100, max 1000). The upstream "
            "Semantic Scholar bulk endpoint may still fetch its larger provider "
            "batch internally, so prefer search_papers or "
            "search_papers_semantic_scholar for small targeted pages."
        ),
    )

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 100, 1000)


class PaperMatchArgs(ToolArgsModel):
    query: str = Field(description="Paper title to find the best match for")
    fields: list[str] | None = Field(default=None, description="Fields to return")


class PaperAutocompleteArgs(ToolArgsModel):
    query: str = Field(description="Partial paper title for typeahead completion")


class PaperLookupArgs(ToolArgsModel):
    paper_id: str = Field(description="Paper ID (DOI, ArXiv ID, S2 ID, etc.)")
    fields: list[str] | None = Field(default=None, description="Fields to return")


class PaperListArgs(PaperLookupArgs):
    paper_id: str = Field(description=SEMANTIC_SCHOLAR_EXPANSION_PAPER_ID_DESCRIPTION)
    limit: int = Field(
        default=100,
        description="Max results (default 100, max 1000)",
    )
    cursor: str | None = Field(
        default=None,
        description=OPAQUE_CURSOR_FIELD_DESCRIPTION,
    )

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 100, 1000)


class PaperAuthorsArgs(ToolArgsModel):
    paper_id: str = Field(description=SEMANTIC_SCHOLAR_EXPANSION_PAPER_ID_DESCRIPTION)
    fields: list[str] | None = Field(default=None, description=AUTHOR_FIELDS_DESCRIPTION)
    limit: int = Field(
        default=100,
        description="Max results (default 100, max 1000)",
    )
    cursor: str | None = Field(
        default=None,
        description=OPAQUE_CURSOR_FIELD_DESCRIPTION,
    )

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 100, 1000)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[str] | None) -> list[str] | None:
        return _validate_author_fields(value)


class AuthorInfoArgs(ToolArgsModel):
    author_id: str = Field(description=AUTHOR_ID_DESCRIPTION)
    fields: list[str] | None = Field(default=None, description=AUTHOR_FIELDS_DESCRIPTION)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[str] | None) -> list[str] | None:
        return _validate_author_fields(value)


class AuthorPapersArgs(AuthorInfoArgs):
    limit: int = Field(
        default=100,
        description="Max results (default 100, max 1000)",
    )
    cursor: str | None = Field(
        default=None,
        description=OPAQUE_CURSOR_FIELD_DESCRIPTION,
    )
    publication_date_or_year: str | None = Field(
        default=None,
        alias="publicationDateOrYear",
        description="Date or date-range filter",
    )

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 100, 1000)


class AuthorSearchArgs(ToolArgsModel):
    query: str = Field(description=AUTHOR_SEARCH_QUERY_DESCRIPTION)
    fields: list[str] | None = Field(default=None, description=AUTHOR_FIELDS_DESCRIPTION)
    limit: int = Field(
        default=10,
        description="Max results (default 10, max 1000)",
    )
    cursor: str | None = Field(
        default=None,
        description=OPAQUE_CURSOR_FIELD_DESCRIPTION,
    )

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 10, 1000)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[str] | None) -> list[str] | None:
        return _validate_author_fields(value)


class BatchGetAuthorsArgs(ToolArgsModel):
    author_ids: list[str] = Field(description="List of author IDs (up to 1000)")
    fields: list[str] | None = Field(default=None, description=AUTHOR_FIELDS_DESCRIPTION)

    @field_validator("author_ids")
    @classmethod
    def validate_author_ids(cls, value: list[str]) -> list[str]:
        if len(value) > 1000:
            raise ValueError(
                f"Maximum 1000 author IDs per batch request, got {len(value)}"
            )
        return value

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[str] | None) -> list[str] | None:
        return _validate_author_fields(value)


class SnippetSearchArgs(ToolArgsModel):
    query: str = Field(description="Text snippet to search for")
    fields: list[str] | None = Field(default=None, description="Fields to return")
    limit: int = Field(
        default=10,
        description="Max results (default 10, max 100)",
    )
    year: str | None = Field(
        default=None,
        description="Year filter, e.g. '2020-2023' or '2023'",
    )
    publication_date_or_year: str | None = Field(
        default=None,
        alias="publicationDateOrYear",
        description="Date or date-range filter",
    )
    fields_of_study: str | None = Field(
        default=None,
        alias="fieldsOfStudy",
        description="Comma-separated fields of study filter",
    )
    min_citation_count: int | None = Field(
        default=None,
        alias="minCitationCount",
        description="Minimum citation count filter",
    )
    venue: str | None = Field(
        default=None,
        description="Comma-separated venue filter",
    )

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 10, 100)


class RecommendationArgs(PaperLookupArgs):
    limit: int = Field(default=10, description="Max results (default 10, max 100)")

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 10, 100)


class PostRecommendationsArgs(ToolArgsModel):
    positive_paper_ids: list[str] = Field(
        alias="positivePaperIds",
        description="Paper IDs to use as positive seeds",
    )
    negative_paper_ids: list[str] | None = Field(
        default=None,
        alias="negativePaperIds",
        description="Paper IDs to use as negative seeds (optional)",
    )
    fields: list[str] | None = Field(default=None, description="Fields to return")
    limit: int = Field(default=10, description="Max results (default 10, max 100)")

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 10, 100)


class BatchGetPapersArgs(ToolArgsModel):
    paper_ids: list[str] = Field(description="List of paper IDs (up to 500)")
    fields: list[str] | None = Field(default=None, description="Fields to return")

    @field_validator("paper_ids")
    @classmethod
    def validate_paper_ids(cls, value: list[str]) -> list[str]:
        if len(value) > 500:
            raise ValueError(
                f"Maximum 500 paper IDs per batch request, got {len(value)}"
            )
        return value


class GetCitationFormatsArgs(ToolArgsModel):
    result_id: str = Field(
        description=(
            "Scholar result_id for the paper. "
            "Use paper.scholarResultId (not paper.sourceId) from a "
            "serpapi_google_scholar search_papers result — "
            "paper.scholarResultId is the raw Scholar result_id and is the "
            "correct identifier for this tool. "
            "paper.sourceId may be a cluster_id or cites_id instead of a "
            "result_id when result_id was absent, so it cannot be used here. "
            "If paper.scholarResultId is absent the paper cannot be used with "
            "this tool. "
            "This is a paid SerpApi request (cached for 1 hour by SerpApi). "
            "Only works when SCHOLAR_SEARCH_ENABLE_SERPAPI=true and "
            "SERPAPI_API_KEY is set."
        ),
    )


TOOL_INPUT_MODELS: dict[str, type[ToolArgsModel]] = {
    "search_papers": SearchPapersArgs,
    "search_papers_core": MinimalProviderSearchPapersArgs,
    "search_papers_semantic_scholar": SemanticProviderSearchPapersArgs,
    "search_papers_serpapi": MinimalProviderSearchPapersArgs,
    "search_papers_arxiv": MinimalProviderSearchPapersArgs,
    "search_papers_bulk": BulkSearchPapersArgs,
    "search_papers_match": PaperMatchArgs,
    "paper_autocomplete": PaperAutocompleteArgs,
    "get_paper_details": PaperLookupArgs,
    "get_paper_citations": PaperListArgs,
    "get_paper_references": PaperListArgs,
    "get_paper_authors": PaperAuthorsArgs,
    "get_author_info": AuthorInfoArgs,
    "get_author_papers": AuthorPapersArgs,
    "search_authors": AuthorSearchArgs,
    "batch_get_authors": BatchGetAuthorsArgs,
    "search_snippets": SnippetSearchArgs,
    "get_paper_recommendations": RecommendationArgs,
    "get_paper_recommendations_post": PostRecommendationsArgs,
    "batch_get_papers": BatchGetPapersArgs,
    "get_paper_citation_formats": GetCitationFormatsArgs,
}
