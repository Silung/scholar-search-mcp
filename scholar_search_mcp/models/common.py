"""Shared Pydantic models for request validation and normalized payloads."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class ApiModel(BaseModel):
    """Base model that preserves unknown provider fields during normalization."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Pagination(BaseModel):
    """Unified pagination envelope present on every list response.

    ``has_more`` tells the caller whether additional pages exist.
    ``next_cursor`` is an opaque token to pass as ``cursor`` in the next tool
    call to retrieve the following page.  Its internal encoding is
    provider-specific and may change between releases; treat it as a black box.

    ``extra="ignore"`` is intentional: the parent model's ``model_validator``
    always recomputes this object from typed fields (``next`` / ``token``), so
    any leftover camelCase keys that arrive when a dict is round-tripped through
    ``dump_jsonable`` are safely discarded without raising.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    has_more: bool = Field(default=False, serialization_alias="hasMore")
    next_cursor: str | None = Field(default=None, serialization_alias="nextCursor")


class Author(ApiModel):
    """Normalized author payload."""

    name: str | None = None


class Paper(ApiModel):
    """Normalized paper payload used across providers."""

    paper_id: str | None = Field(default=None, alias="paperId")
    title: str | None = None
    abstract: str | None = None
    year: int | None = None
    authors: list[Author] = Field(default_factory=list)
    citation_count: int | None = Field(default=None, alias="citationCount")
    reference_count: int | None = Field(default=None, alias="referenceCount")
    influential_citation_count: int | None = Field(
        default=None,
        alias="influentialCitationCount",
    )
    venue: str | None = None
    publication_types: Any = Field(default=None, alias="publicationTypes")
    publication_date: str | None = Field(default=None, alias="publicationDate")
    url: str | None = None
    pdf_url: str | None = Field(default=None, alias="pdfUrl")
    source: str | None = None
    source_id: str | None = Field(default=None, alias="sourceId")
    canonical_id: str | None = Field(default=None, alias="canonicalId")


class BrokerMetadata(BaseModel):
    """Metadata describing the brokered nature of a ``search_papers`` response.

    ``mode`` is always ``"brokered_single_page"`` for ``search_papers``,
    indicating the response is a single-page best-effort result rather than a
    provider-native continuation stream.

    ``provider_used`` identifies which provider supplied the returned results.
    Possible values are ``"core"``, ``"semantic_scholar"``, ``"arxiv"``, or
    ``"none"`` when no provider returned results.

    ``continuation_supported`` is always ``False`` for ``search_papers``; for
    paginated retrieval use ``search_papers_bulk`` or other provider-specific
    tools.
    """

    model_config = ConfigDict(populate_by_name=True)
    mode: str = Field(default="brokered_single_page", serialization_alias="mode")
    provider_used: str = Field(serialization_alias="providerUsed")
    continuation_supported: bool = Field(
        default=False,
        serialization_alias="continuationSupported",
    )
    attempted_providers: list["BrokerAttempt"] = Field(
        default_factory=list,
        serialization_alias="attemptedProviders",
    )
    semantic_scholar_only_filters: list[str] = Field(
        default_factory=list,
        serialization_alias="semanticScholarOnlyFilters",
    )
    recommended_pagination_tool: str = Field(
        default="search_papers_bulk",
        serialization_alias="recommendedPaginationTool",
    )


class BrokerAttempt(BaseModel):
    """One provider decision in the ``search_papers`` broker chain."""

    model_config = ConfigDict(populate_by_name=True)
    provider: str
    status: Literal["returned_results", "returned_no_results", "failed", "skipped"]
    reason: str | None = None


class SearchResponse(ApiModel):
    """Unified response for the ``search_papers`` tool.

    ``search_papers`` is a best-effort convenience tool that tries multiple
    providers in order.  It does **not** support cursor-based pagination because
    different providers use incompatible continuation mechanisms; mixing pages
    from different backends would produce incorrect results.  For paginated
    retrieval use ``search_papers_bulk`` (Semantic Scholar) or other
    provider-specific tools.

    ``broker_metadata`` is populated by the broker when results are returned;
    it is ``None`` only for internal helper paths that do not go through the
    full broker fallback chain.
    """

    total: int = 0
    offset: int = 0
    data: list[Paper] = Field(default_factory=list)
    broker_metadata: BrokerMetadata | None = Field(
        default=None,
        serialization_alias="brokerMetadata",
    )


class SemanticSearchResponse(ApiModel):
    """Semantic Scholar search response."""

    total: int = 0
    offset: int = 0
    next: int | None = None
    data: list[Paper] = Field(default_factory=list)
    pagination: Pagination = Field(
        default_factory=lambda: Pagination(has_more=False),
    )

    @model_validator(mode="after")
    def _compute_pagination(self) -> "SemanticSearchResponse":
        self.pagination = Pagination(
            has_more=self.next is not None,
            next_cursor=str(self.next) if self.next is not None else None,
        )
        return self


class BulkSearchResponse(ApiModel):
    """Semantic Scholar bulk search response (token-paginated)."""

    total: int = 0
    token: str | None = None
    data: list[Paper] = Field(default_factory=list)
    pagination: Pagination = Field(
        default_factory=lambda: Pagination(has_more=False),
    )

    @model_validator(mode="after")
    def _compute_pagination(self) -> "BulkSearchResponse":
        self.pagination = Pagination(
            has_more=self.token is not None,
            next_cursor=self.token,
        )
        return self


class CoreSearchResponse(ApiModel):
    """CORE search response normalized to shared paper entries."""

    total: int = 0
    entries: list[Paper] = Field(default_factory=list)


class ArxivSearchResponse(ApiModel):
    """arXiv search response normalized to shared paper entries."""

    total_results: int = Field(default=0, alias="totalResults")
    entries: list[Paper] = Field(default_factory=list)


class AuthorProfile(ApiModel):
    """Semantic Scholar author response."""

    author_id: str | None = Field(default=None, alias="authorId")
    name: str | None = None
    affiliations: list[str] = Field(default_factory=list)
    homepage: str | None = None
    paper_count: int | None = Field(default=None, alias="paperCount")
    citation_count: int | None = Field(default=None, alias="citationCount")
    h_index: int | None = Field(default=None, alias="hIndex")


class AuthorListResponse(ApiModel):
    """Semantic Scholar offset-paginated author list response."""

    total: int = 0
    offset: int = 0
    next: int | None = None
    data: list[AuthorProfile] = Field(default_factory=list)
    pagination: Pagination = Field(
        default_factory=lambda: Pagination(has_more=False),
    )

    @model_validator(mode="after")
    def _compute_pagination(self) -> "AuthorListResponse":
        self.pagination = Pagination(
            has_more=self.next is not None,
            next_cursor=str(self.next) if self.next is not None else None,
        )
        return self


class BatchAuthorResponse(RootModel[list[AuthorProfile]]):
    """Semantic Scholar batch author lookup response."""


class PaperListResponse(ApiModel):
    """Provider response containing a list of papers under `data`.

    The ``offset`` and ``next`` fields mirror what Semantic Scholar returns for
    offset-paginated sub-resource endpoints (citations, references, author papers).
    ``next`` is the offset to pass in the following call; if absent the current
    page is the last one.
    """

    offset: int = 0
    next: int | None = None
    data: list[Paper] = Field(default_factory=list)
    pagination: Pagination = Field(
        default_factory=lambda: Pagination(has_more=False),
    )

    @model_validator(mode="after")
    def _compute_pagination(self) -> "PaperListResponse":
        self.pagination = Pagination(
            has_more=self.next is not None,
            next_cursor=str(self.next) if self.next is not None else None,
        )
        return self


class PaperAuthorListResponse(ApiModel):
    """Offset-paginated author list for a specific paper."""

    total: int = 0
    offset: int = 0
    next: int | None = None
    data: list[AuthorProfile] = Field(default_factory=list)
    pagination: Pagination = Field(
        default_factory=lambda: Pagination(has_more=False),
    )

    @model_validator(mode="after")
    def _compute_pagination(self) -> "PaperAuthorListResponse":
        self.pagination = Pagination(
            has_more=self.next is not None,
            next_cursor=str(self.next) if self.next is not None else None,
        )
        return self


class SnippetPaper(ApiModel):
    """Minimal paper info embedded in a snippet search result."""

    paper_id: str | None = Field(default=None, alias="paperId")
    title: str | None = None
    year: int | None = None
    url: str | None = None


class SnippetObject(ApiModel):
    """The `snippet` sub-object returned by ``/snippet/search``.

    Per the API guide the snippet result wraps snippet text inside a nested
    ``snippet`` object that can include ``text``, ``snippetKind``, ``section``,
    and annotation data.  Modelling it as a sub-object (instead of hoisting
    ``text`` to the top level) preserves all returned fields.
    """

    text: str | None = None
    snippet_kind: str | None = Field(default=None, alias="snippetKind")
    section: str | None = None


class SnippetResult(ApiModel):
    """One result from ``/snippet/search``.

    The API returns ``{"snippet": {...}, "score": ..., "paper": {...}}``.
    """

    score: float | None = None
    snippet: SnippetObject | None = None
    paper: SnippetPaper | None = None


class SnippetSearchResponse(ApiModel):
    """Response from `/snippet/search`."""

    data: list[SnippetResult] = Field(default_factory=list)


class RecommendationResponse(ApiModel):
    """Semantic Scholar recommendations response."""

    recommended_papers: list[Paper] = Field(
        default_factory=list,
        alias="recommendedPapers",
    )


class CitationFormat(ApiModel):
    """One text citation format (e.g. MLA, APA) returned by
    get_paper_citation_formats."""

    title: str = ""
    snippet: str = ""


class ExportLink(ApiModel):
    """One export download link (e.g. BibTeX, EndNote) returned by
    get_paper_citation_formats."""

    name: str = ""
    link: str = ""


class CitationFormatsResponse(ApiModel):
    """Response from the ``get_paper_citation_formats`` tool.

    ``result_id`` echoes the Scholar result_id used for the lookup.
    ``citations`` contains text citation strings (MLA, APA, Chicago, etc.).
    ``export_links`` contains structured-format download links (BibTeX, etc.).
    ``provider`` identifies the upstream service that supplied the data.
    """

    result_id: str = Field(serialization_alias="resultId")
    citations: list[CitationFormat] = Field(default_factory=list)
    export_links: list[ExportLink] = Field(
        default_factory=list,
        serialization_alias="exportLinks",
    )
    provider: str = "serpapi_google_scholar"


class BatchPaperResponse(RootModel[list[Paper]]):
    """Semantic Scholar batch lookup response."""


def dump_jsonable(value: Any) -> Any:
    """Serialize nested Pydantic models while leaving plain JSON values intact."""

    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True)
    if isinstance(value, list):
        return [dump_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: dump_jsonable(item) for key, item in value.items()}
    return value
