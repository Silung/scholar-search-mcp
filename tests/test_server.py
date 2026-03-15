import json
import xml.etree.ElementTree as ET
from typing import Any

import pytest

import scholar_search_mcp
import scholar_search_mcp.__main__ as server_main
from scholar_search_mcp import server


class DummyResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class DummyAsyncClient:
    def __init__(self, responses: list[DummyResponse]) -> None:
        self._responses = responses
        self.calls = 0

    async def __aenter__(self) -> "DummyAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def request(self, **kwargs) -> DummyResponse:
        response = self._responses[self.calls]
        self.calls += 1
        return response


class RecordingSemanticClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def search_papers(self, **kwargs) -> dict:
        self.calls.append(("search_papers", kwargs))
        return kwargs.pop(
            "_response",
            {"total": 1, "offset": 0, "data": [{"paperId": "semantic-1"}]},
        )

    async def search_papers_bulk(self, **kwargs) -> dict:
        self.calls.append(("search_papers_bulk", kwargs))
        return {"total": 1, "token": None, "data": [{"paperId": "bulk-1"}]}

    async def search_papers_match(self, **kwargs) -> dict:
        self.calls.append(("search_papers_match", kwargs))
        return {"paperId": "match-1", "title": "Best match"}

    async def paper_autocomplete(self, **kwargs) -> dict:
        self.calls.append(("paper_autocomplete", kwargs))
        return {"matches": [{"id": "ac-1", "title": "Autocomplete result"}]}

    async def get_paper_details(self, **kwargs) -> dict:
        self.calls.append(("get_paper_details", kwargs))
        return {"paperId": kwargs["paper_id"]}

    async def get_paper_citations(self, **kwargs) -> dict:
        self.calls.append(("get_paper_citations", kwargs))
        return {"data": [{"paperId": kwargs["paper_id"]}]}

    async def get_paper_references(self, **kwargs) -> dict:
        self.calls.append(("get_paper_references", kwargs))
        return {"data": [{"paperId": kwargs["paper_id"]}]}

    async def get_paper_authors(self, **kwargs) -> dict:
        self.calls.append(("get_paper_authors", kwargs))
        return {"total": 1, "offset": 0, "data": [{"authorId": "a-1"}]}

    async def get_author_info(self, **kwargs) -> dict:
        self.calls.append(("get_author_info", kwargs))
        return {"authorId": kwargs["author_id"]}

    async def get_author_papers(self, **kwargs) -> dict:
        self.calls.append(("get_author_papers", kwargs))
        return {"data": [{"authorId": kwargs["author_id"]}]}

    async def search_authors(self, **kwargs) -> dict:
        self.calls.append(("search_authors", kwargs))
        return {"total": 1, "offset": 0, "data": [{"authorId": "a-1"}]}

    async def batch_get_authors(self, **kwargs) -> list[dict[str, str]]:
        self.calls.append(("batch_get_authors", kwargs))
        return [{"authorId": aid} for aid in kwargs["author_ids"]]

    async def search_snippets(self, **kwargs) -> dict:
        self.calls.append(("search_snippets", kwargs))
        return {"data": [{"score": 0.9, "text": "snippet text"}]}

    async def get_recommendations(self, **kwargs) -> dict:
        self.calls.append(("get_recommendations", kwargs))
        return {"recommendedPapers": [{"paperId": kwargs["paper_id"]}]}

    async def get_recommendations_post(self, **kwargs) -> dict:
        self.calls.append(("get_recommendations_post", kwargs))
        return {"recommendedPapers": [{"paperId": "rec-post-1"}]}

    async def batch_get_papers(self, **kwargs) -> list[dict[str, str]]:
        self.calls.append(("batch_get_papers", kwargs))
        return [{"paperId": paper_id} for paper_id in kwargs["paper_ids"]]


def _payload(response: list) -> Any:
    assert len(response) == 1
    return json.loads(response[0].text)


def test_arxiv_id_from_url_strips_version_suffix() -> None:
    assert (
        server._arxiv_id_from_url("https://arxiv.org/abs/2201.00978v1")
        == "2201.00978"
    )


def test_text_returns_empty_string_for_missing_element() -> None:
    assert server._text(None) == ""


def test_env_bool_parses_common_false_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHOLAR_TEST_BOOL", "false")
    assert server._env_bool("SCHOLAR_TEST_BOOL", True) is False


def test_core_response_to_merged_preserves_total_and_limit() -> None:
    result = server._core_response_to_merged(
        {
            "total": 10,
            "entries": [
                {"paperId": "1", "title": "One", "url": "https://example.com/1"},
                {"paperId": "2", "title": "Two", "url": "https://example.com/2"},
            ],
        },
        limit=1,
    )

    assert result == {
        "total": 10,
        "offset": 0,
        "data": [{"paperId": "1", "title": "One", "url": "https://example.com/1"}],
    }


def test_core_result_to_paper_prefers_doi_url_and_normalizes_metadata() -> None:
    paper = server.CoreApiClient()._result_to_paper(
        {
            "id": 42,
            "doi": "10.1000/example-doi",
            "title": "Example paper",
            "abstract": "Example abstract",
            "publishedDate": "2023-05-01",
            "authors": [{"name": "Author One"}, "Author Two"],
            "journals": [{"title": "Journal A"}, {"title": "Journal B"}],
            "documentType": ["article"],
            "downloadUrl": "https://downloads.example/paper.pdf",
            "citationCount": 7,
        }
    )

    assert paper == {
        "paperId": "42",
        "title": "Example paper",
        "abstract": "Example abstract",
        "year": 2023,
        "authors": [{"name": "Author One"}, {"name": "Author Two"}],
        "citationCount": 7,
        "referenceCount": None,
        "influentialCitationCount": None,
        "venue": "Journal A, Journal B",
        "publicationTypes": ["article"],
        "publicationDate": "2023-05-01",
        "url": "https://doi.org/10.1000/example-doi",
        "pdfUrl": "https://downloads.example/paper.pdf",
        "source": "core",
    }


def test_core_result_to_paper_uses_nested_download_url_variants() -> None:
    paper = server.CoreApiClient()._result_to_paper(
        {
            "id": "core-1",
            "title": "Nested download url",
            "downloadUrl": {"urls": [{"link": "https://downloads.example/from-urls.pdf"}]},
            "authors": [{"name": "Author One"}, {"orcid": "missing-name"}],
        }
    )

    assert paper is not None
    assert paper["url"] == "https://downloads.example/from-urls.pdf"
    assert paper["pdfUrl"] is None
    assert paper["authors"] == [{"name": "Author One"}]
    assert paper["paperId"] == "core-1"


def test_core_result_to_paper_uses_source_fulltext_url_variants() -> None:
    paper = server.CoreApiClient()._result_to_paper(
        {
            "id": "core-2",
            "title": "Source fulltext url",
            "sourceFulltextUrls": {"urls": ["https://fulltext.example/paper"]},
            "downloadUrl": {"url": "https://downloads.example/paper.pdf"},
            "depositedDate": "2022-03-02",
        }
    )

    assert paper is not None
    assert paper["url"] == "https://downloads.example/paper.pdf"
    assert paper["pdfUrl"] == "https://downloads.example/paper.pdf"
    assert paper["publicationDate"] == "2022-03-02"
    assert paper["year"] == 2022


def test_core_result_to_paper_returns_none_without_required_fields() -> None:
    client = server.CoreApiClient()

    assert (
        client._result_to_paper({"id": "core-3", "downloadUrl": "https://x"})
        is None
    )
    assert client._result_to_paper({"title": "Missing url"}) is None


@pytest.mark.asyncio
async def test_list_tools_returns_expected_public_contract() -> None:
    tools = await server.list_tools()

    assert len(tools) == 16
    tool_map = {tool.name: tool for tool in tools}
    assert set(tool_map) == {
        "search_papers",
        "search_papers_bulk",
        "search_papers_match",
        "paper_autocomplete",
        "get_paper_details",
        "get_paper_citations",
        "get_paper_references",
        "get_paper_authors",
        "get_author_info",
        "get_author_papers",
        "search_authors",
        "batch_get_authors",
        "search_snippets",
        "get_paper_recommendations",
        "get_paper_recommendations_post",
        "batch_get_papers",
    }
    assert tool_map["search_papers"].inputSchema["required"] == ["query"]
    assert set(tool_map["search_papers"].inputSchema["properties"]) == {
        "query",
        "limit",
        "fields",
        "year",
        "venue",
        "publicationDateOrYear",
        "fieldsOfStudy",
        "publicationTypes",
        "openAccessPdf",
        "minCitationCount",
    }
    assert tool_map["batch_get_papers"].inputSchema["required"] == ["paper_ids"]
    assert tool_map["batch_get_authors"].inputSchema["required"] == ["author_ids"]
    post_rec_schema = tool_map["get_paper_recommendations_post"].inputSchema
    assert "positivePaperIds" in post_rec_schema["required"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_call", "expected_payload"),
    [
        (
            "get_paper_details",
            {"paper_id": "paper-1", "fields": ["title"]},
            ("get_paper_details", {"paper_id": "paper-1", "fields": ["title"]}),
            {"paperId": "paper-1"},
        ),
        (
            "get_paper_citations",
            {"paper_id": "paper-2"},
            (
                "get_paper_citations",
                {"paper_id": "paper-2", "limit": 100, "fields": None, "offset": None},
            ),
            {"data": [{"paperId": "paper-2"}]},
        ),
        (
            "get_paper_references",
            {"paper_id": "paper-3", "limit": 12, "fields": ["authors"]},
            (
                "get_paper_references",
                {
                    "paper_id": "paper-3",
                    "limit": 12,
                    "fields": ["authors"],
                    "offset": None,
                },
            ),
            {"data": [{"paperId": "paper-3"}]},
        ),
        (
            "get_author_info",
            {"author_id": "author-1"},
            ("get_author_info", {"author_id": "author-1", "fields": None}),
            {"authorId": "author-1"},
        ),
        (
            "get_author_papers",
            {"author_id": "author-2", "limit": 25},
            (
                "get_author_papers",
                {
                    "author_id": "author-2",
                    "limit": 25,
                    "fields": None,
                    "offset": None,
                    "publication_date_or_year": None,
                },
            ),
            {"data": [{"authorId": "author-2"}]},
        ),
        (
            "get_paper_recommendations",
            {"paper_id": "paper-4"},
            (
                "get_recommendations",
                {"paper_id": "paper-4", "limit": 10, "fields": None},
            ),
            {"recommendedPapers": [{"paperId": "paper-4"}]},
        ),
        (
            "batch_get_papers",
            {"paper_ids": ["p1", "p2"], "fields": ["title"]},
            (
                "batch_get_papers",
                {"paper_ids": ["p1", "p2"], "fields": ["title"]},
            ),
            [{"paperId": "p1"}, {"paperId": "p2"}],
        ),
    ],
)
async def test_call_tool_routes_non_search_tools(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict,
    expected_call: tuple[str, dict],
    expected_payload: dict | list,
) -> None:
    fake_client = RecordingSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    payload = _payload(await server.call_tool(tool_name, arguments))

    assert fake_client.calls == [expected_call]
    assert payload == expected_payload


@pytest.mark.asyncio
async def test_search_papers_forwards_clamped_semantic_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = RecordingSemanticClient()

    monkeypatch.setattr(server, "enable_core", False)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_arxiv", False)
    monkeypatch.setattr(server, "client", fake_client)

    payload = _payload(
        await server.call_tool(
            "search_papers",
            {
                "query": "graph neural networks",
                "limit": 999,
                "fields": ["title", "year"],
                "year": "2022",
                "venue": ["NeurIPS"],
            },
        )
    )

    assert fake_client.calls == [
        (
            "search_papers",
            {
                "query": "graph neural networks",
                "limit": 100,
                "fields": ["title", "year"],
                "year": "2022",
                "venue": ["NeurIPS"],
                "publication_date_or_year": None,
                "fields_of_study": None,
                "publication_types": None,
                "open_access_pdf": None,
                "min_citation_count": None,
            },
        )
    ]
    assert payload["data"][0]["source"] == "semantic_scholar"


def test_package_entrypoints_stay_aligned() -> None:
    assert scholar_search_mcp.main is server.main
    assert server_main.main is server.main


def test_merge_search_results_deduplicates_arxiv_entries() -> None:
    merged = server._merge_search_results(
        {
            "offset": 3,
            "data": [
                {
                    "paperId": "semantic-1",
                    "title": "Known paper",
                    "externalIds": {"ArXiv": "1234.5678"},
                }
            ],
        },
        {
            "entries": [
                {"paperId": "1234.5678", "title": "Known paper from arXiv"},
                {"paperId": "9999.0001", "title": "Unique arXiv paper"},
            ]
        },
        limit=5,
    )

    assert merged["offset"] == 3
    assert merged["total"] == 2
    assert [paper["paperId"] for paper in merged["data"]] == [
        "semantic-1",
        "9999.0001",
    ]
    assert merged["data"][0]["source"] == "semantic_scholar"


def test_arxiv_entry_to_paper_extracts_expected_fields() -> None:
    entry = ET.fromstring(
        """
        <entry xmlns=\"http://www.w3.org/2005/Atom\" xmlns:arxiv=\"http://arxiv.org/schemas/atom\">
          <id>http://arxiv.org/abs/2201.00978v2</id>
          <title> Sample Title </title>
          <summary> Sample abstract </summary>
          <published>2024-01-15T00:00:00Z</published>
          <author><name>Author One</name></author>
          <link rel=\"alternate\" href=\"https://arxiv.org/abs/2201.00978v2\" />
                    <link
                        rel=\"related\"
                        title=\"pdf\"
                        href=\"https://arxiv.org/pdf/2201.00978v2.pdf\"
                    />
          <arxiv:primary_category term=\"cs.AI\" />
        </entry>
        """
    )

    paper = server.ArxivClient()._entry_to_paper(entry)

    assert paper is not None
    assert paper["paperId"] == "2201.00978"
    assert paper["title"] == "Sample Title"
    assert paper["year"] == 2024
    assert paper["venue"] == "cs.AI"
    assert paper["pdfUrl"] == "https://arxiv.org/pdf/2201.00978v2.pdf"


@pytest.mark.asyncio
async def test_call_tool_raises_for_unknown_tool() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await server.call_tool("unknown_tool", {})


@pytest.mark.asyncio
async def test_call_tool_search_papers_returns_empty_when_all_channels_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "enable_core", False)
    monkeypatch.setattr(server, "enable_semantic_scholar", False)
    monkeypatch.setattr(server, "enable_arxiv", False)

    response = await server.call_tool("search_papers", {"query": "transformers"})

    assert len(response) == 1
    assert '"total": 0' in response[0].text
    assert '"data": []' in response[0].text


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
async def test_search_papers_falls_back_from_core_to_semantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCoreClient:
        async def search(self, **kwargs) -> dict:
            raise RuntimeError("core unavailable")

    class SemanticClient:
        async def search_papers(self, **kwargs) -> dict:
            return {
                "total": 1,
                "offset": 0,
                "data": [{"paperId": "s2-1", "title": "Fallback paper"}],
            }

    monkeypatch.setattr(server, "enable_core", True)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_arxiv", True)
    monkeypatch.setattr(server, "core_client", FailingCoreClient())
    monkeypatch.setattr(server, "client", SemanticClient())

    response = await server.call_tool("search_papers", {"query": "fallback"})
    payload = json.loads(response[0].text)

    assert payload["total"] == 1
    assert payload["data"][0]["paperId"] == "s2-1"
    assert payload["data"][0]["source"] == "semantic_scholar"


@pytest.mark.asyncio
async def test_search_papers_falls_back_to_arxiv_when_other_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCoreClient:
        async def search(self, **kwargs) -> dict:
            raise RuntimeError("core unavailable")

    class FailingSemanticClient:
        async def search_papers(self, **kwargs) -> dict:
            raise RuntimeError("semantic unavailable")

    class ArxivClient:
        async def search(self, **kwargs) -> dict:
            return {
                "totalResults": 1,
                "entries": [
                    {
                        "paperId": "arxiv-1",
                        "title": "arXiv fallback paper",
                        "url": "https://arxiv.org/abs/arxiv-1",
                        "source": "arxiv",
                    }
                ],
            }

    monkeypatch.setattr(server, "enable_core", True)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_arxiv", True)
    monkeypatch.setattr(server, "core_client", FailingCoreClient())
    monkeypatch.setattr(server, "client", FailingSemanticClient())
    monkeypatch.setattr(server, "arxiv_client", ArxivClient())

    response = await server.call_tool("search_papers", {"query": "fallback"})
    payload = json.loads(response[0].text)

    assert payload["total"] == 1
    assert payload["data"][0]["paperId"] == "arxiv-1"
    assert payload["data"][0]["source"] == "arxiv"


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
@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_method", "check_payload"),
    [
        (
            "search_papers_bulk",
            {"query": "neural networks", "limit": 50},
            "search_papers_bulk",
            lambda p: p["data"][0]["paperId"] == "bulk-1",
        ),
        (
            "search_papers_match",
            {"query": "attention is all you need"},
            "search_papers_match",
            lambda p: p["paperId"] == "match-1",
        ),
        (
            "paper_autocomplete",
            {"query": "transformer"},
            "paper_autocomplete",
            lambda p: "matches" in p,
        ),
        (
            "get_paper_authors",
            {"paper_id": "paper-5"},
            "get_paper_authors",
            lambda p: p["total"] == 1,
        ),
        (
            "search_authors",
            {"query": "Yoshua Bengio"},
            "search_authors",
            lambda p: p["total"] == 1,
        ),
        (
            "batch_get_authors",
            {"author_ids": ["a1", "a2"]},
            "batch_get_authors",
            lambda p: len(p) == 2,
        ),
        (
            "search_snippets",
            {"query": "deep learning"},
            "search_snippets",
            lambda p: len(p["data"]) == 1,
        ),
        (
            "get_paper_recommendations_post",
            {"positivePaperIds": ["p1", "p2"]},
            "get_recommendations_post",
            lambda p: p["recommendedPapers"][0]["paperId"] == "rec-post-1",
        ),
    ],
)
async def test_call_tool_routes_new_tools(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict,
    expected_method: str,
    check_payload,
) -> None:
    fake_client = RecordingSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    payload = _payload(await server.call_tool(tool_name, arguments))

    assert any(method == expected_method for method, _ in fake_client.calls), (
        f"Expected {expected_method!r} to have been called; got {fake_client.calls}"
    )
    assert check_payload(payload)


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


@pytest.mark.asyncio
async def test_search_papers_exposes_new_filter_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = RecordingSemanticClient()
    monkeypatch.setattr(server, "enable_core", False)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_arxiv", False)
    monkeypatch.setattr(server, "client", fake_client)

    await server.call_tool(
        "search_papers",
        {
            "query": "ml",
            "publicationDateOrYear": "2020:2023",
            "fieldsOfStudy": "Computer Science",
            "minCitationCount": 5,
        },
    )

    assert len(fake_client.calls) == 1
    method, kwargs = fake_client.calls[0]
    assert method == "search_papers"
    assert kwargs["publication_date_or_year"] == "2020:2023"
    assert kwargs["fields_of_study"] == "Computer Science"
    assert kwargs["min_citation_count"] == 5


# ---------------------------------------------------------------------------
# Tests addressing review issues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_papers_skips_core_when_ss_only_filter_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CORE must be bypassed whenever a Semantic Scholar-only filter is used.

    Regression guard for the issue where CORE would be called first and return
    page-1 un-filtered results despite the caller requesting a Semantic Scholar-
    specific filter.
    """

    class SpyCoreClient:
        def __init__(self) -> None:
            self.called = False

        async def search(self, **kwargs) -> dict:
            self.called = True
            return {
                "total": 1,
                "entries": [
                    {
                        "paperId": "core-1",
                        "title": "Core result",
                        "url": "https://example.com",
                    }
                ],
            }

    class SuccessSemanticClient:
        async def search_papers(self, **kwargs) -> dict:
            return {
                "total": 1,
                "offset": 0,
                "data": [{"paperId": "s2-result"}],
            }

    spy_core = SpyCoreClient()

    monkeypatch.setattr(server, "enable_core", True)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_arxiv", False)
    monkeypatch.setattr(server, "core_client", spy_core)
    monkeypatch.setattr(server, "client", SuccessSemanticClient())

    # publicationDateOrYear is an SS-only filter; CORE must be skipped.
    response = await server.call_tool(
        "search_papers",
        {"query": "neural nets", "publicationDateOrYear": "2020:2024"},
    )
    payload = json.loads(response[0].text)

    assert not spy_core.called, "CORE should have been skipped for SS-only filter"
    assert payload["data"][0]["paperId"] == "s2-result"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_filter",
    [
        {"publicationDateOrYear": "2020:2023"},
        {"fieldsOfStudy": "Computer Science"},
        {"publicationTypes": "JournalArticle"},
        {"openAccessPdf": True},
        {"minCitationCount": 10},
    ],
)
async def test_search_papers_ss_filters_always_bypass_core(
    monkeypatch: pytest.MonkeyPatch,
    extra_filter: dict,
) -> None:
    """Each individual SS-only filter independently causes CORE to be bypassed."""

    class SpyCoreClient:
        def __init__(self) -> None:
            self.called = False

        async def search(self, **kwargs) -> dict:
            self.called = True
            return {"total": 0, "entries": []}

    class SemanticClient:
        async def search_papers(self, **kwargs) -> dict:
            return {"total": 0, "offset": 0, "data": []}

    spy_core = SpyCoreClient()
    monkeypatch.setattr(server, "enable_core", True)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_arxiv", False)
    monkeypatch.setattr(server, "core_client", spy_core)
    monkeypatch.setattr(server, "client", SemanticClient())

    await server.call_tool("search_papers", {"query": "test", **extra_filter})

    assert not spy_core.called, (
        f"CORE should be skipped when filter {extra_filter} is set"
    )


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


# ---------------------------------------------------------------------------
# Pagination metadata tests
# ---------------------------------------------------------------------------


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

    # search_papers is non-paginated; its description must NOT mention cursor
    # but it should explain the limitation and point to the bulk alternative
    sp_desc = TOOL_DESCRIPTIONS["search_papers"]
    assert "cursor" not in sp_desc
    assert "pagination" in sp_desc or "search_papers_bulk" in sp_desc


# ---------------------------------------------------------------------------
# Unified cursor abstraction tests
# ---------------------------------------------------------------------------


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

    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        await server.call_tool(
            "get_paper_citations",
            {"paper_id": "paper-1", "cursor": "tok-bulk-token"},
        )

    assert fake_client.calls == [], "SS client must not be called for an invalid cursor"


def test_search_papers_rejects_cursor_argument() -> None:
    """search_papers input model must reject cursor as an unknown field."""
    from pydantic import ValidationError

    from scholar_search_mcp.models.tools import SearchPapersArgs

    with pytest.raises(ValidationError):
        SearchPapersArgs.model_validate({"query": "ml", "cursor": "10"})


@pytest.mark.asyncio
async def test_search_papers_response_has_no_pagination_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """search_papers is non-paginated; response must not contain a pagination key."""

    class CoreClient:
        async def search(self, **kwargs) -> dict:
            return {
                "total": 2,
                "entries": [
                    {"paperId": "c1", "title": "Paper", "url": "https://x.com/1"},
                ],
            }

    monkeypatch.setattr(server, "enable_core", True)
    monkeypatch.setattr(server, "enable_semantic_scholar", False)
    monkeypatch.setattr(server, "enable_arxiv", False)
    monkeypatch.setattr(server, "core_client", CoreClient())

    response = await server.call_tool("search_papers", {"query": "test"})
    payload = json.loads(response[0].text)

    assert "pagination" not in payload
    assert set(payload.keys()) == {"total", "offset", "data"}
