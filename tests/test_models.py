import pytest


def test_batch_get_papers_rejects_oversized_list() -> None:
    """batch_get_papers must raise a validation error for lists > 500."""
    from pydantic import ValidationError

    from scholar_search_mcp.models.tools import BatchGetPapersArgs

    with pytest.raises(ValidationError, match="500"):
        BatchGetPapersArgs(paper_ids=[f"p{i}" for i in range(501)])


def test_batch_get_authors_rejects_oversized_list() -> None:
    """batch_get_authors must raise a validation error for lists > 1000."""
    from pydantic import ValidationError

    from scholar_search_mcp.models.tools import BatchGetAuthorsArgs

    with pytest.raises(ValidationError, match="1000"):
        BatchGetAuthorsArgs(author_ids=[f"a{i}" for i in range(1001)])


def test_snippet_result_model_preserves_nested_snippet() -> None:
    """SnippetResult must keep the snippet sub-object, not hoist text to the top."""
    from scholar_search_mcp.models import SnippetResult

    raw = {
        "score": 0.95,
        "snippet": {
            "text": "deep learning has transformed",
            "snippetKind": "result",
            "section": "Introduction",
        },
        "paper": {"paperId": "abc123", "title": "DL Survey"},
    }
    result = SnippetResult.model_validate(raw)

    assert result.score == 0.95
    assert result.snippet is not None
    assert result.snippet.text == "deep learning has transformed"
    assert result.snippet.snippet_kind == "result"
    assert result.snippet.section == "Introduction"
    assert result.paper is not None
    assert result.paper.paper_id == "abc123"


def test_semantic_search_response_preserves_next_field() -> None:
    """SemanticSearchResponse must propagate the next offset and pagination envelope."""
    from scholar_search_mcp.models import SemanticSearchResponse

    raw = {
        "total": 500,
        "offset": 10,
        "next": 20,
        "data": [{"paperId": "p1", "title": "Paper One"}],
    }
    parsed = SemanticSearchResponse.model_validate(raw)
    dumped = parsed.model_dump(by_alias=True)

    assert dumped["next"] == 20
    assert dumped["offset"] == 10
    assert dumped["total"] == 500
    assert dumped["pagination"] == {"hasMore": True, "nextCursor": "20"}


def test_semantic_search_response_next_is_none_when_absent() -> None:
    """next must be None and hasMore False when the API omits it (last page)."""
    from scholar_search_mcp.models import SemanticSearchResponse

    raw = {"total": 5, "offset": 0, "data": [{"paperId": "p1"}]}
    parsed = SemanticSearchResponse.model_validate(raw)

    assert parsed.next is None
    assert parsed.pagination.has_more is False
    assert parsed.pagination.next_cursor is None


def test_paper_list_response_preserves_offset_and_next() -> None:
    """PaperListResponse must carry offset, next, and the pagination envelope."""
    from scholar_search_mcp.models import PaperListResponse

    raw = {
        "offset": 100,
        "next": 200,
        "data": [{"paperId": "citing-1"}],
    }
    parsed = PaperListResponse.model_validate(raw)
    dumped = parsed.model_dump(by_alias=True)

    assert dumped["offset"] == 100
    assert dumped["next"] == 200
    assert len(dumped["data"]) == 1
    assert dumped["pagination"] == {"hasMore": True, "nextCursor": "200"}


def test_paper_list_response_next_is_none_on_last_page() -> None:
    """next must default to None and hasMore False on the last page."""
    from scholar_search_mcp.models import PaperListResponse

    raw = {"offset": 900, "data": [{"paperId": "last-paper"}]}
    parsed = PaperListResponse.model_validate(raw)

    assert parsed.next is None
    assert parsed.offset == 900
    assert parsed.pagination.has_more is False


def test_pagination_model_camelcase_serialization() -> None:
    """Pagination fields must serialize to camelCase for API consistency."""
    from scholar_search_mcp.models import Pagination

    p = Pagination(has_more=True, next_cursor="42")
    dumped = p.model_dump(by_alias=True)

    assert dumped == {"hasMore": True, "nextCursor": "42"}


def test_pagination_model_has_more_false_when_no_cursor() -> None:
    """Pagination with no cursor must have hasMore=False."""
    from scholar_search_mcp.models import Pagination

    p = Pagination(has_more=False)
    assert p.has_more is False
    assert p.next_cursor is None


def test_bulk_search_response_pagination_uses_token() -> None:
    """BulkSearchResponse pagination must encode the token as nextCursor."""
    from scholar_search_mcp.models import BulkSearchResponse

    raw = {"total": 5000, "token": "tok-abc123", "data": []}
    parsed = BulkSearchResponse.model_validate(raw)

    assert parsed.pagination.has_more is True
    assert parsed.pagination.next_cursor == "tok-abc123"


def test_bulk_search_response_no_token_means_last_page() -> None:
    """BulkSearchResponse without a token means hasMore=False."""
    from scholar_search_mcp.models import BulkSearchResponse

    raw = {"total": 100, "data": [{"paperId": "p1"}]}
    parsed = BulkSearchResponse.model_validate(raw)

    assert parsed.pagination.has_more is False
    assert parsed.pagination.next_cursor is None


def test_citation_formats_response_model_serializes_correctly() -> None:
    """CitationFormatsResponse must serialize with camelCase aliases."""
    from scholar_search_mcp.models import CitationFormatsResponse
    from scholar_search_mcp.models.common import CitationFormat, ExportLink

    resp = CitationFormatsResponse(
        result_id="r-001",
        citations=[CitationFormat(title="MLA", snippet="Smith...")],
        export_links=[ExportLink(name="BibTeX", link="https://example.com/bib")],
    )
    dumped = resp.model_dump(by_alias=True)

    assert dumped["resultId"] == "r-001"
    assert dumped["provider"] == "serpapi_google_scholar"
    assert dumped["citations"][0]["title"] == "MLA"
    assert dumped["exportLinks"][0]["name"] == "BibTeX"


def test_paper_scholar_result_id_is_first_class_field() -> None:
    """Paper.scholarResultId must be a first-class schema field, not just an extra.

    Agents rely on seeing scholarResultId in the schema to know they can pass it
    to get_paper_citation_formats. This test guards against regressions where the
    field is demoted back to an extra dict entry (invisible in schema).
    """
    from scholar_search_mcp.models.common import Paper

    schema = Paper.model_json_schema()
    props = schema.get("properties", {})

    assert "scholarResultId" in props, (
        "scholarResultId must be a first-class field in the Paper model schema "
        "so agents can discover it without reading long tool descriptions."
    )
    field_schema = props["scholarResultId"]
    description = field_schema.get("description", "")
    assert description, (
        "scholarResultId must have a non-empty description in the schema "
        "so agents understand when to use it and which tool to pass it to."
    )
    assert "get_paper_citation_formats" in description, (
        "scholarResultId description must mention get_paper_citation_formats "
        "so agents can follow the citation export golden path."
    )


def test_paper_scholar_result_id_set_for_serpapi_results() -> None:
    """Paper.scholarResultId must be set on SerpApi results and None otherwise."""
    from scholar_search_mcp.models.common import Paper

    # SerpApi result: scholarResultId set from result_id
    serpapi_paper = Paper(
        title="Test Paper",
        source="serpapi_google_scholar",
        scholarResultId="rid-abc",
    )
    assert serpapi_paper.scholar_result_id == "rid-abc"
    dumped = serpapi_paper.model_dump(by_alias=True)
    assert dumped["scholarResultId"] == "rid-abc"

    # Non-SerpApi result: scholarResultId is None
    core_paper = Paper(title="CORE Paper", source="core")
    assert core_paper.scholar_result_id is None
    core_dumped = core_paper.model_dump(by_alias=True)
    assert core_dumped["scholarResultId"] is None


def test_broker_metadata_next_step_hint_is_provider_specific() -> None:
    """BrokerMetadata.nextStepHint must vary by provider to guide agents."""
    from scholar_search_mcp.search import _metadata

    serpapi_meta = _metadata(
        provider_used="serpapi_google_scholar",
        attempts=[],
        ss_only_filters=[],
    )
    assert "scholarResultId" in serpapi_meta.next_step_hint
    assert "get_paper_citation_formats" in serpapi_meta.next_step_hint
    assert "pivot rather than another page from SerpApi Google Scholar" in (
        serpapi_meta.next_step_hint
    )

    none_meta = _metadata(
        provider_used="none",
        attempts=[],
        ss_only_filters=[],
    )
    assert "broaden" in none_meta.next_step_hint.lower()

    ss_meta = _metadata(
        provider_used="semantic_scholar",
        attempts=[],
        ss_only_filters=[],
    )
    assert "search_papers_bulk" in ss_meta.next_step_hint
    assert "get_paper_citations" in ss_meta.next_step_hint
    assert "closest continuation path" in ss_meta.next_step_hint

    venue_meta = _metadata(
        provider_used="semantic_scholar",
        attempts=[],
        ss_only_filters=[],
        venue=["NeurIPS"],
    )
    assert "semantic pivot" in venue_meta.next_step_hint
    assert "does not preserve venue filtering" in venue_meta.next_step_hint

    core_meta = _metadata(
        provider_used="core",
        attempts=[],
        ss_only_filters=[],
    )
    assert "pivot rather than another page from CORE" in core_meta.next_step_hint


def test_broker_metadata_next_step_hint_in_serialized_response() -> None:
    """brokerMetadata.nextStepHint must appear in the serialized search response."""
    from scholar_search_mcp.models.common import SearchResponse
    from scholar_search_mcp.search import _dump_search_response, _metadata

    meta = _metadata(
        provider_used="semantic_scholar",
        attempts=[],
        ss_only_filters=[],
    )
    response = SearchResponse(total=1, offset=0, data=[], broker_metadata=meta)
    serialized = _dump_search_response(response)

    assert "brokerMetadata" in serialized
    assert "nextStepHint" in serialized["brokerMetadata"]
    assert serialized["brokerMetadata"]["nextStepHint"]
