import pytest

from scholar_search_mcp import server
from tests.helpers import DummyAsyncClient, DummyResponse


@pytest.mark.asyncio
async def test_semantic_scholar_request_retries_after_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        DummyResponse(status_code=429, headers={"Retry-After": "0"}),
        DummyResponse(status_code=200, payload={"data": [{"paperId": "ok"}]}),
    ]
    dummy_client = DummyAsyncClient(responses)
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: dummy_client)
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    client = server.SemanticScholarClient(api_key="test-key")
    result = await client._request("GET", "paper/search", params={"query": "test"})

    assert result == {"data": [{"paperId": "ok"}]}
    assert dummy_client.calls == 2
    assert 1.0 in sleep_calls  # the 429 back-off delay was honored
    # _pace() fires before every attempt, so there must be a second sleep
    # for the pacing guard on the retry.
    assert len(sleep_calls) == 2


@pytest.mark.asyncio
async def test_semantic_scholar_rate_limiter_paces_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared rate limiter must insert a sleep when requests arrive faster
    than the configured minimum interval."""
    responses = [
        DummyResponse(status_code=200, payload={"data": [{"paperId": "r1"}]}),
        DummyResponse(status_code=200, payload={"data": [{"paperId": "r2"}]}),
    ]
    dummy_client = DummyAsyncClient(responses)
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    call_count = 0

    def fake_monotonic() -> float:
        # Simulate two calls within 0.1 s of each other to trigger pacing.
        # First call (inside _pace for request-1): now = 0.0 → no prior request,
        # sets _last_request_time = 0.0.
        # Second call (inside _pace for request-2): now = 0.0 → elapsed = 0.0
        # → sleep needed.  Subsequent calls return a large value so _pace exits.
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return 0.0
        return 100.0

    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: dummy_client)
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        "scholar_search_mcp.clients.semantic_scholar.client.time.monotonic",
        fake_monotonic,
    )

    sc = server.SemanticScholarClient(api_key="test-key")
    # First request – sets _last_request_time to 0.0; no sleep needed.
    await sc._request("GET", "paper/search", params={"query": "a"})
    # Second request – monotonic() still returns 0.0 so elapsed < MIN_INTERVAL.
    await sc._request("GET", "paper/search", params={"query": "b"})

    # At least one pacing sleep must have been issued.
    assert any(s > 0 for s in sleep_calls)


@pytest.mark.asyncio
async def test_get_recommendations_uses_recommendations_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_recommendations must target the recommendations API, not the graph API."""
    captured: list[str] = []

    async def fake_sleep(_: float) -> None:
        pass

    class CapturingAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, *, method, url, **kwargs):
            captured.append(url)
            return DummyResponse(
                status_code=200,
                payload={"recommendedPapers": [{"paperId": "rec-1"}]},
            )

    monkeypatch.setattr(
        server.httpx,
        "AsyncClient",
        lambda timeout: CapturingAsyncClient(),
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    await sc.get_recommendations("paper-xyz")

    assert len(captured) == 1
    assert "recommendations" in captured[0]
    assert "graph" not in captured[0]


@pytest.mark.asyncio
async def test_semantic_scholar_request_repaces_on_429_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pacing guard must fire before every attempt, including 429 retries."""
    responses = [
        DummyResponse(status_code=429, headers={"Retry-After": "0"}),
        DummyResponse(status_code=200, payload={"data": [{"paperId": "ok"}]}),
    ]
    dummy_client = DummyAsyncClient(responses)
    pace_calls: list[str] = []
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    original_pace = server.SemanticScholarClient._pace

    async def recording_pace(self: server.SemanticScholarClient) -> None:
        pace_calls.append("pace")
        await original_pace(self)

    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: dummy_client)
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(server.SemanticScholarClient, "_pace", recording_pace)

    sc = server.SemanticScholarClient(api_key="test-key")
    result = await sc._request("GET", "paper/search", params={"query": "test"})

    assert result == {"data": [{"paperId": "ok"}]}
    # _pace must be called once for the initial attempt and once for the retry.
    assert len(pace_calls) == 2, (
        f"Expected 2 _pace calls (initial + retry), got {len(pace_calls)}"
    )
    # The 429 back-off sleep and the pacing sleep for the retry must both fire.
    assert 1.0 in sleep_calls, "429 back-off sleep was not honoured"
    assert len(sleep_calls) == 2, (
        f"Expected 2 sleep calls (429 back-off + pacing), got {len(sleep_calls)}"
    )


@pytest.mark.asyncio
async def test_get_paper_citations_response_includes_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_paper_citations end-to-end: pagination fields must survive the full path."""

    async def fake_sleep(_: float) -> None:
        pass

    class PaginatingAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return DummyResponse(
                status_code=200,
                payload={
                    "offset": 0,
                    "next": 100,
                    "data": [{"paperId": "citing-paper-1", "title": "Citing paper"}],
                },
            )

    monkeypatch.setattr(
        server.httpx, "AsyncClient", lambda timeout: PaginatingAsyncClient()
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    result = await sc.get_paper_citations("paper-xyz", limit=100)

    assert result["offset"] == 0
    assert result["next"] == 100
    assert result["data"][0]["paperId"] == "citing-paper-1"
    # Uniform pagination envelope must be present
    assert result["pagination"]["hasMore"] is True
    assert result["pagination"]["nextCursor"] == "100"


@pytest.mark.asyncio
async def test_get_author_papers_response_includes_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_author_papers end-to-end: pagination fields must survive the full path."""

    async def fake_sleep(_: float) -> None:
        pass

    class PaginatingAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return DummyResponse(
                status_code=200,
                payload={
                    "offset": 50,
                    "next": 100,
                    "data": [{"paperId": "author-paper-1", "title": "Author paper"}],
                },
            )

    monkeypatch.setattr(
        server.httpx, "AsyncClient", lambda timeout: PaginatingAsyncClient()
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    result = await sc.get_author_papers("author-abc", limit=50, offset=50)

    assert result["offset"] == 50
    assert result["next"] == 100
    assert result["data"][0]["paperId"] == "author-paper-1"
    # Uniform pagination envelope must be present
    assert result["pagination"]["hasMore"] is True
    assert result["pagination"]["nextCursor"] == "100"


@pytest.mark.asyncio
async def test_search_papers_response_includes_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """search_papers end-to-end: the next field must be preserved in the response."""

    async def fake_sleep(_: float) -> None:
        pass

    class NextPageAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return DummyResponse(
                status_code=200,
                payload={
                    "total": 300,
                    "offset": 10,
                    "next": 20,
                    "data": [{"paperId": "s2-page2-1", "title": "Result"}],
                },
            )

    monkeypatch.setattr(
        server.httpx, "AsyncClient", lambda timeout: NextPageAsyncClient()
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    result = await sc.search_papers("transformers", limit=10, offset=10)

    assert result["total"] == 300
    assert result["offset"] == 10
    assert result["next"] == 20
    # Uniform pagination envelope must be present
    assert result["pagination"]["hasMore"] is True
    assert result["pagination"]["nextCursor"] == "20"


def test_search_papers_match_unwraps_nested_match_payload() -> None:
    client = server.SemanticScholarClient()

    normalized = client._normalize_match_response(
        {
            "paperId": None,
            "title": None,
            "data": [
                {
                    "paperId": "match-123",
                    "title": "Wrapped best match",
                }
            ],
        }
    )

    assert normalized.paper_id == "match-123"
    assert normalized.title == "Wrapped best match"
    assert "data" not in normalized.model_dump(by_alias=True, exclude_none=True)
