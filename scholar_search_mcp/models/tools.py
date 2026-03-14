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

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 10, 100)


class PaperLookupArgs(ToolArgsModel):
    paper_id: str = Field(description="Paper ID (DOI, ArXiv ID, S2 ID, etc.)")
    fields: list[str] | None = Field(default=None, description="Fields to return")


class PaperListArgs(PaperLookupArgs):
    limit: int = Field(
        default=100,
        description="Max results (default 100, max 1000)",
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

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 100, 1000)


class RecommendationArgs(PaperLookupArgs):
    limit: int = Field(default=10, description="Max results (default 10, max 100)")

    @field_validator("limit", mode="before")
    @classmethod
    def clamp_limit(cls, value: int | None) -> int:
        return _clamp_limit(value, 10, 100)


class BatchGetPapersArgs(ToolArgsModel):
    paper_ids: list[str] = Field(description="List of paper IDs")
    fields: list[str] | None = Field(default=None, description="Fields to return")


TOOL_INPUT_MODELS: dict[str, type[ToolArgsModel]] = {
    "search_papers": SearchPapersArgs,
    "get_paper_details": PaperLookupArgs,
    "get_paper_citations": PaperListArgs,
    "get_paper_references": PaperListArgs,
    "get_author_info": AuthorInfoArgs,
    "get_author_papers": AuthorPapersArgs,
    "get_paper_recommendations": RecommendationArgs,
    "batch_get_papers": BatchGetPapersArgs,
}