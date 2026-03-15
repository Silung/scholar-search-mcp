import pytest

from scholar_search_mcp import server
from tests.helpers import RecordingSemanticClient


@pytest.mark.asyncio
async def test_search_papers_bulk_passes_cursor_as_token_and_sort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = RecordingSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    await server.call_tool(
        "search_papers_bulk",
        {"query": "language models", "cursor": "tok-abc", "sort": "citationCount"},
    )

    assert len(fake_client.calls) == 1
    method, kwargs = fake_client.calls[0]
    assert method == "search_papers_bulk"
    # cursor is decoded to token in the SS client call
    assert kwargs["token"] == "tok-abc"
    assert kwargs["sort"] == "citationCount"


def test_tool_descriptions_document_cursor_pagination_uniformly() -> None:
    """All paginated tool descriptions must explain the cursor / pagination pattern."""
    from scholar_search_mcp.tools import TOOL_DESCRIPTIONS

    paginated_tools = [
        "search_papers_bulk",
        "get_paper_citations",
        "get_paper_references",
        "get_paper_authors",
        "get_author_papers",
        "search_authors",
    ]
    for name in paginated_tools:
        desc = TOOL_DESCRIPTIONS[name]
        assert "cursor" in desc, (
            f"Tool '{name}' description should mention the 'cursor' parameter"
        )
        assert "hasMore" in desc or "nextCursor" in desc, (
            f"Tool '{name}' description should mention hasMore or nextCursor"
        )
        assert "opaque" in desc, (
            f"Tool '{name}' description should describe nextCursor as opaque"
        )
        assert "exactly as returned" in desc, (
            f"Tool '{name}' description should tell clients to reuse cursors unchanged"
        )
        assert "do not derive, edit, or fabricate" in desc, (
            f"Tool '{name}' description should tell clients not to synthesize cursors"
        )

    # search_papers is non-paginated; its description must NOT mention cursor
    # but it should explain the limitation and point to the bulk alternative
    sp_desc = TOOL_DESCRIPTIONS["search_papers"]
    assert "cursor" not in sp_desc
    assert "pagination" in sp_desc or "search_papers_bulk" in sp_desc


def test_cursor_to_offset_decoding() -> None:
    """_cursor_to_offset must decode integer strings and reject invalid cursors."""
    from scholar_search_mcp.dispatch import _cursor_to_offset

    assert _cursor_to_offset("42") == 42
    assert _cursor_to_offset("0") == 0
    assert _cursor_to_offset(None) is None

    # Non-integer cursors (e.g. bulk-search tokens or stale cursors) must raise
    # instead of silently resetting to page 1.
    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        _cursor_to_offset("not-a-number")

    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        _cursor_to_offset("tok-abc123")


@pytest.mark.asyncio
async def test_bulk_search_cursor_decoded_to_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cursor='tok-xyz' must arrive at the SS client as token='tok-xyz'."""
    fake_client = RecordingSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    await server.call_tool(
        "search_papers_bulk",
        {"query": "deep learning", "cursor": "tok-xyz"},
    )

    assert len(fake_client.calls) == 1
    method, kwargs = fake_client.calls[0]
    assert method == "search_papers_bulk"
    assert kwargs["token"] == "tok-xyz"


@pytest.mark.asyncio
async def test_get_paper_citations_cursor_decoded_to_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cursor='100' in get_paper_citations must reach the SS client as offset=100."""
    fake_client = RecordingSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    await server.call_tool(
        "get_paper_citations",
        {"paper_id": "paper-1", "cursor": "100"},
    )

    assert len(fake_client.calls) == 1
    method, kwargs = fake_client.calls[0]
    assert method == "get_paper_citations"
    assert kwargs["offset"] == 100


@pytest.mark.asyncio
async def test_invalid_cursor_raises_tool_error_on_offset_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-integer cursor on an offset-based tool must raise ValueError."""
    fake_client = RecordingSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    with pytest.raises(ValueError, match="Invalid pagination cursor") as exc_info:
        await server.call_tool(
            "get_paper_citations",
            {"paper_id": "paper-1", "cursor": "tok-bulk-token"},
        )

    message = str(exc_info.value)
    assert "pagination.nextCursor" in message
    assert "exactly as returned" in message
    assert "derive, edit, or fabricate" in message
    assert fake_client.calls == [], "SS client must not be called for an invalid cursor"


def test_search_papers_rejects_cursor_argument() -> None:
    """search_papers input model must reject cursor as an unknown field."""
    from pydantic import ValidationError

    from scholar_search_mcp.models.tools import SearchPapersArgs

    with pytest.raises(ValidationError):
        SearchPapersArgs.model_validate({"query": "ml", "cursor": "10"})


def test_encode_cursor_produces_decodable_base64() -> None:
    """encode_cursor must produce a URL-safe base64 string that decodes back."""
    from scholar_search_mcp.utils.cursor import encode_cursor

    payload = {
        "tool": "get_paper_citations",
        "provider": "semantic_scholar",
        "offset": 100,
        "version": 1,
    }
    encoded = encode_cursor(payload)
    assert isinstance(encoded, str)

    # Must be URL-safe base64 (no +, /, or = padding issues)
    import base64

    decoded_bytes = base64.urlsafe_b64decode(encoded)
    import json

    decoded = json.loads(decoded_bytes)
    assert decoded == payload


def test_decode_cursor_returns_cursor_state() -> None:
    """decode_cursor must return a CursorState with all fields populated."""
    from scholar_search_mcp.utils.cursor import (
        CursorState,
        decode_cursor,
        encode_cursor,
    )

    encoded = encode_cursor(
        {
            "tool": "get_paper_references",
            "provider": "semantic_scholar",
            "offset": 200,
            "version": 1,
        }
    )
    state = decode_cursor(encoded)

    assert isinstance(state, CursorState)
    assert state.tool == "get_paper_references"
    assert state.provider == "semantic_scholar"
    assert state.offset == 200
    assert state.version == 1
    assert state.context_hash is None


def test_is_legacy_offset_detects_integer_strings() -> None:
    """is_legacy_offset must return True for integer strings only."""
    from scholar_search_mcp.utils.cursor import is_legacy_offset

    assert is_legacy_offset("0") is True
    assert is_legacy_offset("100") is True
    assert is_legacy_offset("999999") is True
    # Structured cursors and token strings are not legacy offsets
    assert is_legacy_offset("tok-abc123") is False
    assert is_legacy_offset("not-a-number") is False


def test_is_legacy_offset_false_for_structured_cursor() -> None:
    """Structured cursors must NOT be identified as legacy offsets."""
    from scholar_search_mcp.utils.cursor import encode_cursor, is_legacy_offset

    encoded = encode_cursor(
        {
            "tool": "search_authors",
            "provider": "semantic_scholar",
            "offset": 50,
            "version": 1,
        }
    )
    assert is_legacy_offset(encoded) is False


def test_cursor_to_offset_accepts_legacy_integer() -> None:
    """_cursor_to_offset must accept legacy plain integer string cursors."""
    from scholar_search_mcp.dispatch import _cursor_to_offset

    assert _cursor_to_offset("0", "get_paper_citations") == 0
    assert _cursor_to_offset("100", "get_paper_citations") == 100


def test_cursor_to_offset_accepts_structured_cursor() -> None:
    """_cursor_to_offset must decode structured cursors and return their offset."""
    from scholar_search_mcp.dispatch import _cursor_to_offset
    from scholar_search_mcp.utils.cursor import cursor_from_offset

    encoded = cursor_from_offset("get_paper_citations", 150)
    result = _cursor_to_offset(encoded, "get_paper_citations")
    assert result == 150


def test_cursor_to_offset_rejects_cross_tool_cursor() -> None:
    """_cursor_to_offset must reject a cursor issued by a different tool."""
    from scholar_search_mcp.dispatch import _cursor_to_offset
    from scholar_search_mcp.utils.cursor import cursor_from_offset

    # Cursor was issued by get_paper_citations but used with get_paper_references
    encoded = cursor_from_offset("get_paper_citations", 100)
    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        _cursor_to_offset(encoded, "get_paper_references")


def test_cursor_to_offset_rejects_corrupted_cursor() -> None:
    """_cursor_to_offset must reject a corrupted base64 cursor."""
    from scholar_search_mcp.dispatch import _cursor_to_offset

    corrupted = "not-valid-base64!!!"
    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        _cursor_to_offset(corrupted, "get_paper_citations")


def test_cursor_to_offset_returns_none_for_none() -> None:
    """_cursor_to_offset must return None when no cursor is given."""
    from scholar_search_mcp.dispatch import _cursor_to_offset

    assert _cursor_to_offset(None, "get_paper_citations") is None
    # cursor=None returns None immediately regardless of tool; safe to omit tool
    assert _cursor_to_offset(None) is None


def test_cursor_to_offset_rejects_negative_integer() -> None:
    """_cursor_to_offset must reject negative integer strings as invalid offsets."""
    from scholar_search_mcp.dispatch import _cursor_to_offset

    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        _cursor_to_offset("-1", "get_paper_citations")

    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        _cursor_to_offset("-100", "search_authors")


@pytest.mark.asyncio
async def test_offset_tool_response_has_structured_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offset-backed tool responses must return structured (non-integer) nextCursor."""
    import base64
    import json

    class PaginatedSemanticClient(RecordingSemanticClient):
        async def get_paper_citations(self, **kwargs):
            self.calls.append(("get_paper_citations", kwargs))
            # Return the same format the real SS client produces (already serialized
            # PaperListResponse with pagination key)
            from scholar_search_mcp.models.common import (
                PaperListResponse,
                dump_jsonable,
            )

            return dump_jsonable(
                PaperListResponse.model_validate(
                    {"data": [{"paperId": "p1"}], "offset": 0, "next": 100}
                )
            )

    fake_client = PaginatedSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    result = await server.call_tool(
        "get_paper_citations",
        {"paper_id": "paper-1"},
    )
    payload = json.loads(result[0].text)

    cursor = payload["pagination"]["nextCursor"]
    assert cursor is not None
    # Must be a structured cursor (not a plain integer string)
    assert not cursor.isdigit()
    # Must decode to valid CursorState referencing the correct tool
    decoded_bytes = base64.urlsafe_b64decode(cursor)
    decoded = json.loads(decoded_bytes)
    assert decoded["tool"] == "get_paper_citations"
    assert decoded["provider"] == "semantic_scholar"
    assert decoded["offset"] == 100


@pytest.mark.asyncio
async def test_structured_cursor_round_trip_on_offset_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A structured cursor returned from page 1 must work as input for page 2."""
    import json

    call_count = 0

    class RoundTripClient(RecordingSemanticClient):
        async def get_paper_citations(self, **kwargs):
            nonlocal call_count
            call_count += 1
            self.calls.append(("get_paper_citations", kwargs))
            from scholar_search_mcp.models.common import (
                PaperListResponse,
                dump_jsonable,
            )

            if call_count == 1:
                return dump_jsonable(
                    PaperListResponse.model_validate(
                        {"data": [{"paperId": "p1"}], "offset": 0, "next": 100}
                    )
                )
            return dump_jsonable(
                PaperListResponse.model_validate(
                    {"data": [{"paperId": "p2"}], "offset": 100, "next": None}
                )
            )

    fake_client = RoundTripClient()
    monkeypatch.setattr(server, "client", fake_client)

    # First page
    result1 = await server.call_tool("get_paper_citations", {"paper_id": "paper-1"})
    page1 = json.loads(result1[0].text)
    cursor = page1["pagination"]["nextCursor"]
    assert cursor is not None

    # Second page: pass structured cursor back
    result2 = await server.call_tool(
        "get_paper_citations",
        {"paper_id": "paper-1", "cursor": cursor},
    )
    page2 = json.loads(result2[0].text)
    assert page2["pagination"]["hasMore"] is False

    # Second call must have received offset=100
    _, second_kwargs = fake_client.calls[1]
    assert second_kwargs["offset"] == 100


@pytest.mark.asyncio
async def test_cross_tool_cursor_reuse_raises_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cursor from get_paper_citations must be rejected by get_paper_references."""
    import json

    class PaginatedSemanticClient(RecordingSemanticClient):
        async def get_paper_citations(self, **kwargs):
            self.calls.append(("get_paper_citations", kwargs))
            from scholar_search_mcp.models.common import (
                PaperListResponse,
                dump_jsonable,
            )

            return dump_jsonable(
                PaperListResponse.model_validate(
                    {"data": [{"paperId": "p1"}], "offset": 0, "next": 100}
                )
            )

    fake_client = PaginatedSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    # Get a cursor from citations tool
    result = await server.call_tool("get_paper_citations", {"paper_id": "paper-1"})
    payload = json.loads(result[0].text)
    citations_cursor = payload["pagination"]["nextCursor"]

    # Try to use it with references tool – must fail
    with pytest.raises(ValueError, match="INVALID_CURSOR") as exc_info:
        await server.call_tool(
            "get_paper_references",
            {"paper_id": "paper-1", "cursor": citations_cursor},
        )

    message = str(exc_info.value)
    assert "pagination.nextCursor" in message
    assert "exactly as returned" in message
    assert "different tool" in message


@pytest.mark.asyncio
async def test_legacy_integer_cursor_still_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy integer cursors must be accepted for backward compatibility."""
    fake_client = RecordingSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    await server.call_tool(
        "get_paper_citations",
        {"paper_id": "paper-1", "cursor": "100"},
    )

    assert len(fake_client.calls) == 1
    _, kwargs = fake_client.calls[0]
    assert kwargs["offset"] == 100


def test_bulk_search_cursor_not_structured() -> None:
    """Bulk search tokens must NOT be treated as offset cursors."""
    from scholar_search_mcp.utils.cursor import is_legacy_offset

    # A bulk search token (provider-issued) is not a legacy offset
    assert is_legacy_offset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh") is False


def test_decode_cursor_rejects_missing_required_fields() -> None:
    """decode_cursor must raise if a required field is absent."""
    import base64
    import json

    from scholar_search_mcp.utils.cursor import decode_cursor

    # Missing 'tool' key
    payload = {"provider": "semantic_scholar", "offset": 50, "version": 1}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode("ascii")

    with pytest.raises(ValueError, match="Corrupted pagination cursor"):
        decode_cursor(encoded)


def test_encode_then_decode_roundtrip() -> None:
    """encode_cursor followed by decode_cursor must reproduce the original state."""
    from scholar_search_mcp.utils.cursor import (
        CursorState,
        decode_cursor,
        encode_cursor,
    )

    original = {
        "tool": "search_authors",
        "provider": "semantic_scholar",
        "offset": 30,
        "version": 1,
    }
    encoded = encode_cursor(original)
    state = decode_cursor(encoded)

    assert state == CursorState(
        tool="search_authors",
        provider="semantic_scholar",
        offset=30,
        version=1,
        context_hash=None,
    )


def test_cursor_to_offset_rejects_wrong_provider() -> None:
    """_cursor_to_offset must reject a cursor with an unexpected provider."""
    import base64
    import json

    from scholar_search_mcp.dispatch import _cursor_to_offset

    payload = {
        "tool": "get_paper_citations",
        "provider": "arxiv",  # wrong provider
        "offset": 100,
        "version": 1,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode("ascii")

    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        _cursor_to_offset(encoded, "get_paper_citations")


def test_cursor_to_offset_rejects_unsupported_version() -> None:
    """_cursor_to_offset must reject a cursor with an unsupported schema version."""
    import base64
    import json

    from scholar_search_mcp.dispatch import _cursor_to_offset

    payload = {
        "tool": "get_paper_citations",
        "provider": "semantic_scholar",
        "offset": 100,
        "version": 99,  # future unsupported version
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode("ascii")

    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        _cursor_to_offset(encoded, "get_paper_citations")


def test_cursor_to_offset_rejects_context_hash_mismatch() -> None:
    """_cursor_to_offset must reject a cursor whose context_hash doesn't match."""
    from scholar_search_mcp.dispatch import _cursor_to_offset
    from scholar_search_mcp.utils.cursor import cursor_from_offset

    # Cursor was issued for paper-1
    encoded = cursor_from_offset(
        "get_paper_citations",
        100,
        context_hash="aabbccdd11223344",
    )
    # Current request is for paper-2 (different context hash)
    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        _cursor_to_offset(
            encoded,
            "get_paper_citations",
            context_hash="deadbeeffeedface",
        )


def test_cursor_to_offset_accepts_matching_context_hash() -> None:
    """_cursor_to_offset must accept a cursor with a matching context_hash."""
    from scholar_search_mcp.dispatch import _cursor_to_offset
    from scholar_search_mcp.utils.cursor import cursor_from_offset

    ctx = "aabbccdd11223344"
    encoded = cursor_from_offset("search_authors", 50, context_hash=ctx)
    result = _cursor_to_offset(encoded, "search_authors", context_hash=ctx)
    assert result == 50


def test_cursor_to_offset_accepts_cursor_without_context_hash() -> None:
    """A cursor without a context_hash must be accepted even when context is provided.

    This covers structured cursors that predate context-hash binding (forward-compat).
    """
    from scholar_search_mcp.dispatch import _cursor_to_offset
    from scholar_search_mcp.utils.cursor import cursor_from_offset

    # Cursor with no context_hash (context_hash=None)
    encoded = cursor_from_offset("get_author_papers", 200, context_hash=None)
    result = _cursor_to_offset(
        encoded,
        "get_author_papers",
        context_hash="some-current-hash",
    )
    assert result == 200


def test_compute_context_hash_is_deterministic() -> None:
    """compute_context_hash must return the same value for the same arguments."""
    from scholar_search_mcp.utils.cursor import compute_context_hash

    h1 = compute_context_hash("get_paper_citations", {"paper_id": "abc123"})
    h2 = compute_context_hash("get_paper_citations", {"paper_id": "abc123"})
    assert h1 == h2
    assert h1 is not None
    assert len(h1) == 16


def test_compute_context_hash_differs_for_different_args() -> None:
    """compute_context_hash must differ when the stream-defining argument changes."""
    from scholar_search_mcp.utils.cursor import compute_context_hash

    h1 = compute_context_hash("get_paper_citations", {"paper_id": "paper-1"})
    h2 = compute_context_hash("get_paper_citations", {"paper_id": "paper-2"})
    assert h1 != h2


def test_compute_context_hash_ignores_cursor_and_limit() -> None:
    """compute_context_hash must produce the same hash regardless of cursor/limit."""
    from scholar_search_mcp.utils.cursor import compute_context_hash

    base = {"paper_id": "p1"}
    with_cursor = {"paper_id": "p1", "cursor": "100", "limit": 50}
    assert compute_context_hash("get_paper_citations", base) == compute_context_hash(
        "get_paper_citations", with_cursor
    )


def test_cursor_from_offset_embeds_context_hash() -> None:
    """cursor_from_offset must embed the context_hash when provided."""
    import base64
    import json

    from scholar_search_mcp.utils.cursor import cursor_from_offset

    ctx = "deadbeeffeedface"
    encoded = cursor_from_offset("search_authors", 30, context_hash=ctx)
    payload = json.loads(base64.urlsafe_b64decode(encoded))
    assert payload["context_hash"] == ctx


def test_cursor_from_offset_omits_context_hash_when_none() -> None:
    """cursor_from_offset must omit context_hash key when not provided."""
    import base64
    import json

    from scholar_search_mcp.utils.cursor import cursor_from_offset

    encoded = cursor_from_offset("search_authors", 30)
    payload = json.loads(base64.urlsafe_b64decode(encoded))
    assert "context_hash" not in payload


@pytest.mark.asyncio
async def test_context_hash_mismatch_rejects_cursor_on_different_paper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cursor issued for paper-1 must be rejected when used for paper-2."""
    import json

    class PaginatedSemanticClient(RecordingSemanticClient):
        async def get_paper_citations(self, **kwargs):
            self.calls.append(("get_paper_citations", kwargs))
            from scholar_search_mcp.models.common import (
                PaperListResponse,
                dump_jsonable,
            )

            return dump_jsonable(
                PaperListResponse.model_validate(
                    {
                        "data": [{"paperId": kwargs["paper_id"]}],
                        "offset": 0,
                        "next": 100,
                    }
                )
            )

    fake_client = PaginatedSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    # Get cursor for paper-1
    result1 = await server.call_tool("get_paper_citations", {"paper_id": "paper-1"})
    page1 = json.loads(result1[0].text)
    cursor = page1["pagination"]["nextCursor"]

    # Use that cursor for paper-2 – must fail due to context_hash mismatch
    with pytest.raises(ValueError, match="INVALID_CURSOR") as exc_info:
        await server.call_tool(
            "get_paper_citations",
            {"paper_id": "paper-2", "cursor": cursor},
        )

    message = str(exc_info.value)
    assert "pagination.nextCursor" in message
    assert "exactly as returned" in message
    assert "different query context" in message


@pytest.mark.asyncio
async def test_context_hash_same_paper_accepts_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cursor issued for paper-1 must be accepted when reused for paper-1."""
    import json

    call_count = 0

    class PaginatedSemanticClient(RecordingSemanticClient):
        async def get_paper_citations(self, **kwargs):
            nonlocal call_count
            call_count += 1
            self.calls.append(("get_paper_citations", kwargs))
            from scholar_search_mcp.models.common import (
                PaperListResponse,
                dump_jsonable,
            )

            if call_count == 1:
                return dump_jsonable(
                    PaperListResponse.model_validate(
                        {"data": [{"paperId": "p1"}], "offset": 0, "next": 100}
                    )
                )
            return dump_jsonable(
                PaperListResponse.model_validate(
                    {"data": [{"paperId": "p2"}], "offset": 100, "next": None}
                )
            )

    fake_client = PaginatedSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    # Page 1
    result1 = await server.call_tool("get_paper_citations", {"paper_id": "paper-1"})
    page1 = json.loads(result1[0].text)
    cursor = page1["pagination"]["nextCursor"]

    # Page 2 – same paper, same context, must succeed
    result2 = await server.call_tool(
        "get_paper_citations",
        {"paper_id": "paper-1", "cursor": cursor},
    )
    page2 = json.loads(result2[0].text)
    assert page2["pagination"]["hasMore"] is False
    _, second_kwargs = fake_client.calls[1]
    assert second_kwargs["offset"] == 100
