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
        "offset",
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
                "offset": None,
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
    assert sleep_calls == [1.0]


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
async def test_search_papers_bulk_passes_token_and_sort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = RecordingSemanticClient()
    monkeypatch.setattr(server, "client", fake_client)

    await server.call_tool(
        "search_papers_bulk",
        {"query": "language models", "token": "tok-abc", "sort": "citationCount"},
    )

    assert len(fake_client.calls) == 1
    method, kwargs = fake_client.calls[0]
    assert method == "search_papers_bulk"
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
            "offset": 10,
            "publicationDateOrYear": "2020:2023",
            "fieldsOfStudy": "Computer Science",
            "minCitationCount": 5,
        },
    )

    assert len(fake_client.calls) == 1
    method, kwargs = fake_client.calls[0]
    assert method == "search_papers"
    assert kwargs["offset"] == 10
    assert kwargs["publication_date_or_year"] == "2020:2023"
    assert kwargs["fields_of_study"] == "Computer Science"
    assert kwargs["min_citation_count"] == 5
