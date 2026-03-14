import json
import xml.etree.ElementTree as ET

import pytest

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
