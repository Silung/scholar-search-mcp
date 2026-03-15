"""Typed tool argument models and schema registry."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolArgsModel(BaseModel):
    """Base MCP tool input model."""

    model_config = ConfigDict(extra="forbid")


def _clamp_limit(value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default
    return min(max(int(value), 1), maximum)


class SearchPapersArgs(ToolArgsModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, description="Max results (default 10, max 100)")
    fields: list[str] | None = Field(default=None, description="Fields to return")
    year: str | None = Field(
        default=None,
        description="Year filter, e.g. '2020-2023' or '2023'",
    )
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

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 10, 100)


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
            "(a provider-issued token for bulk search). Omit to start a new search."
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
        description="Max papers per call (default 100, max 1000)",
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
    limit: int = Field(
        default=100,
        description="Max results (default 100, max 1000)",
    )
    cursor: str | None = Field(
        default=None,
        description=(
            "Continuation cursor from a previous response's "
            "pagination.nextCursor (a stringified integer offset). "
            "Omit to start from the beginning."
        ),
    )

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 100, 1000)


class PaperAuthorsArgs(ToolArgsModel):
    paper_id: str = Field(description="Paper ID")
    fields: list[str] | None = Field(default=None, description="Fields to return")
    limit: int = Field(
        default=100,
        description="Max results (default 100, max 1000)",
    )
    cursor: str | None = Field(
        default=None,
        description=(
            "Continuation cursor from a previous response's "
            "pagination.nextCursor (a stringified integer offset). "
            "Omit to start from the beginning."
        ),
    )

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 100, 1000)


class AuthorInfoArgs(ToolArgsModel):
    author_id: str = Field(description="Author ID")
    fields: list[str] | None = Field(default=None, description="Fields to return")


class AuthorPapersArgs(AuthorInfoArgs):
    limit: int = Field(
        default=100,
        description="Max results (default 100, max 1000)",
    )
    cursor: str | None = Field(
        default=None,
        description=(
            "Continuation cursor from a previous response's "
            "pagination.nextCursor (a stringified integer offset). "
            "Omit to start from the beginning."
        ),
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
    query: str = Field(description="Author name to search for")
    fields: list[str] | None = Field(default=None, description="Fields to return")
    limit: int = Field(
        default=10,
        description="Max results (default 10, max 1000)",
    )
    cursor: str | None = Field(
        default=None,
        description=(
            "Continuation cursor from a previous response's "
            "pagination.nextCursor (a stringified integer offset). "
            "Omit to start from the beginning."
        ),
    )

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 10, 1000)


class BatchGetAuthorsArgs(ToolArgsModel):
    author_ids: list[str] = Field(description="List of author IDs (up to 1000)")
    fields: list[str] | None = Field(default=None, description="Fields to return")

    @field_validator("author_ids")
    @classmethod
    def validate_author_ids(cls, value: list[str]) -> list[str]:
        if len(value) > 1000:
            raise ValueError(
                f"Maximum 1000 author IDs per batch request, got {len(value)}"
            )
        return value


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
