import pytest

from scholar_search_mcp import server
from scholar_search_mcp.transport import httpx
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
async def test_search_papers_bulk_truncates_provider_oversized_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk search must honor small limits even if the provider ignores them."""

    async def fake_sleep(_: float) -> None:
        pass

    oversized_batch = [
        {"paperId": f"bulk-{index}", "title": f"Paper {index}"}
        for index in range(10)
    ]

    class BulkAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return DummyResponse(
                status_code=200,
                payload={
                    "total": 5000,
                    "token": "tok-next",
                    "data": oversized_batch,
                },
            )

    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: BulkAsyncClient())
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    result = await sc.search_papers_bulk("graph neural networks", limit=5)

    assert len(result["data"]) == 5
    assert [paper["paperId"] for paper in result["data"]] == [
        "bulk-0",
        "bulk-1",
        "bulk-2",
        "bulk-3",
        "bulk-4",
    ]
    assert result["pagination"]["hasMore"] is True
    assert result["pagination"]["nextCursor"] == "tok-next"
    assert result["token"] == "tok-next"


@pytest.mark.asyncio
async def test_semantic_scholar_request_retries_with_pacing_on_429(
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
async def test_get_paper_citations_unwraps_nested_citing_paper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_: float) -> None:
        pass

    class NestedCitationsAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return DummyResponse(
                status_code=200,
                payload={
                    "offset": 0,
                    "data": [
                        {
                            "paperId": None,
                            "title": None,
                            "citingPaper": {
                                "paperId": "citing-paper-1",
                                "title": "Wrapped citing paper",
                            },
                        }
                    ],
                },
            )

    monkeypatch.setattr(
        server.httpx, "AsyncClient", lambda timeout: NestedCitationsAsyncClient()
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    result = await sc.get_paper_citations("paper-xyz", limit=1)

    assert result["data"][0]["paperId"] == "citing-paper-1"
    assert result["data"][0]["title"] == "Wrapped citing paper"
    assert "citingPaper" not in result["data"][0]


@pytest.mark.asyncio
async def test_get_paper_references_unwraps_nested_cited_paper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_: float) -> None:
        pass

    class NestedReferencesAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return DummyResponse(
                status_code=200,
                payload={
                    "offset": 0,
                    "data": [
                        {
                            "paperId": None,
                            "title": None,
                            "citedPaper": {
                                "paperId": "referenced-paper-1",
                                "title": "Wrapped reference",
                            },
                        }
                    ],
                },
            )

    monkeypatch.setattr(
        server.httpx, "AsyncClient", lambda timeout: NestedReferencesAsyncClient()
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    result = await sc.get_paper_references("paper-xyz", limit=1)

    assert result["data"][0]["paperId"] == "referenced-paper-1"
    assert result["data"][0]["title"] == "Wrapped reference"
    assert "citedPaper" not in result["data"][0]


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


@pytest.mark.asyncio
async def test_search_papers_match_falls_back_to_fuzzy_search_on_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_: float) -> None:
        pass

    requests: list[tuple[str, str]] = []
    responses = [
        httpx.Response(
            status_code=404,
            request=httpx.Request(
                "GET", "https://api.semanticscholar.org/graph/v1/paper/search/match"
            ),
        ),
        httpx.Response(
            status_code=200,
            request=httpx.Request(
                "GET", "https://api.semanticscholar.org/graph/v1/paper/search"
            ),
            json={
                "total": 1,
                "offset": 0,
                "data": [
                    {
                        "paperId": "paper-1",
                        "title": (
                            "Oyster Cultch Recruit Patterns Provide New Insight "
                            "Into the Restoration and Management of a Critical "
                            "Resource"
                        ),
                    }
                ],
            },
        ),
    ]

    class SequencedAsyncClient:
        def __init__(self, queued_responses: list[httpx.Response]) -> None:
            self._responses = queued_responses

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, *, url: str, params, **kwargs):
            requests.append((url, params["query"]))
            return self._responses.pop(0)

    monkeypatch.setattr(
        server.httpx,
        "AsyncClient",
        lambda timeout: SequencedAsyncClient(responses),
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    result = await sc.search_papers_match(
        "Oyster Cultch-Recruit Patterns Provide New Insight Into the "
        "Restoration and Management of a Critical Resource"
    )

    assert result["paperId"] == "paper-1"
    assert result["matchFound"] is True
    assert result["matchStrategy"] == "fuzzy_search"
    assert requests[0][0].endswith("/paper/search/match")
    assert requests[1][0].endswith("/paper/search")


@pytest.mark.asyncio
async def test_search_papers_match_returns_structured_no_match_payload_after_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_: float) -> None:
        pass

    responses = [
        httpx.Response(
            status_code=404,
            request=httpx.Request(
                "GET", "https://api.semanticscholar.org/graph/v1/paper/search/match"
            ),
        ),
        httpx.Response(
            status_code=200,
            request=httpx.Request(
                "GET", "https://api.semanticscholar.org/graph/v1/paper/search"
            ),
            json={"total": 1, "offset": 0, "data": [{"title": "Unrelated result"}]},
        ),
        httpx.Response(
            status_code=200,
            request=httpx.Request(
                "GET", "https://api.semanticscholar.org/graph/v1/paper/search"
            ),
            json={"total": 0, "offset": 0, "data": []},
        ),
    ]

    class SequencedAsyncClient:
        def __init__(self, queued_responses: list[httpx.Response]) -> None:
            self._responses = queued_responses

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return self._responses.pop(0)

    monkeypatch.setattr(
        server.httpx,
        "AsyncClient",
        lambda timeout: SequencedAsyncClient(responses),
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    result = await sc.search_papers_match("ezMCDA: An Interactive Dashboard")

    assert result["paperId"] is None
    assert result["matchFound"] is False
    assert result["matchStrategy"] == "none"
    assert "outside the indexed paper surface" in result["message"]
    assert result["normalizedQueriesTried"] == [
        "ezMCDA: An Interactive Dashboard",
        "ezMCDA An Interactive Dashboard",
    ]


def test_normalize_author_search_query_falls_back_to_original_when_empty() -> None:
    client = server.SemanticScholarClient()

    normalized = client._normalize_author_search_query('  ""  ')

    assert normalized == '""'


@pytest.mark.asyncio
async def test_search_authors_normalizes_exact_name_punctuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """search_authors should sanitize exact-name punctuation before the request."""
    captured_queries: list[str] = []

    async def fake_sleep(_: float) -> None:
        pass

    class CapturingAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, *, params, **kwargs):
            captured_queries.append(params["query"])
            return DummyResponse(
                status_code=200,
                payload={"total": 1, "offset": 0, "data": [{"authorId": "9191855"}]},
            )

    monkeypatch.setattr(
        server.httpx, "AsyncClient", lambda timeout: CapturingAsyncClient()
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    result = await sc.search_authors("Ryan L. Perroy")

    assert captured_queries == ["Ryan L Perroy"]
    assert result["data"][0]["authorId"] == "9191855"


@pytest.mark.asyncio
async def test_search_authors_400_error_mentions_common_name_disambiguation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_: float) -> None:
        pass

    response = httpx.Response(
        status_code=400,
        request=httpx.Request(
            "GET", "https://api.semanticscholar.org/graph/v1/author/search"
        ),
    )

    class RejectingAuthorSearchAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return response

    monkeypatch.setattr(
        server.httpx,
        "AsyncClient",
        lambda timeout: RejectingAuthorSearchAsyncClient(),
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    with pytest.raises(ValueError, match="affiliation, coauthor, venue, or topic"):
        await sc.search_authors('"Matthew Richardson" "SWCA"')


@pytest.mark.asyncio
async def test_get_author_info_surfaces_actionable_404_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_: float) -> None:
        pass

    request = httpx.Request(
        "GET", "https://api.semanticscholar.org/graph/v1/author/9191855"
    )
    response = httpx.Response(status_code=404, request=request)

    class MissingAuthorAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return response

    monkeypatch.setattr(
        server.httpx, "AsyncClient", lambda timeout: MissingAuthorAsyncClient()
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    with pytest.raises(ValueError, match="Use a Semantic Scholar authorId"):
        await sc.get_author_info("9191855")


@pytest.mark.asyncio
async def test_get_paper_authors_surfaces_portability_hint_for_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_: float) -> None:
        pass

    request = httpx.Request(
        "GET", "https://api.semanticscholar.org/graph/v1/paper/170189535/authors"
    )
    response = httpx.Response(status_code=404, request=request)

    class MissingPaperAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return response

    monkeypatch.setattr(
        server.httpx, "AsyncClient", lambda timeout: MissingPaperAsyncClient()
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    with pytest.raises(ValueError, match="paper.recommendedExpansionId"):
        await sc.get_paper_authors("170189535")


@pytest.mark.asyncio
async def test_search_snippets_degrades_provider_400_to_empty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_: float) -> None:
        pass

    response = httpx.Response(
        status_code=400,
        request=httpx.Request(
            "GET", "https://api.semanticscholar.org/graph/v1/snippet/search"
        ),
    )

    class RejectingSnippetAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def request(self, **kwargs):
            return response

    monkeypatch.setattr(
        server.httpx,
        "AsyncClient",
        lambda timeout: RejectingSnippetAsyncClient(),
    )
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    sc = server.SemanticScholarClient()
    result = await sc.search_snippets('"exact phrase query"')

    assert result["data"] == []
    assert result["degraded"] is True
    assert result["providerStatusCode"] == 400
    assert "search_papers_match/search_papers" in result["message"]
