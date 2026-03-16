import pytest

from scholar_search_mcp import server
from tests.helpers import DummyResponse


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
        "sourceId": "42",
        "canonicalId": "10.1000/example-doi",
        "recommendedExpansionId": "10.1000/example-doi",
        "expansionIdStatus": "portable",
        "scholarResultId": None,
    }


def test_core_result_to_paper_uses_nested_download_url_variants() -> None:
    paper = server.CoreApiClient()._result_to_paper(
        {
            "id": "core-1",
            "title": "Nested download url",
            "downloadUrl": {
                "urls": [{"link": "https://downloads.example/from-urls.pdf"}]
            },
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

    assert client._result_to_paper({"id": "core-3", "downloadUrl": "https://x"}) is None
    assert client._result_to_paper({"title": "Missing url"}) is None


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


def test_core_paper_has_provenance_fields_with_doi() -> None:
    """CORE papers with a DOI must prefer the DOI as canonicalId."""
    paper = server.CoreApiClient()._result_to_paper(
        {
            "id": 98765,
            "doi": "10.1234/core-test",
            "title": "CORE Provenance Test",
            "downloadUrl": "https://core.ac.uk/download/pdf/98765.pdf",
        }
    )

    assert paper is not None
    assert paper["source"] == "core"
    assert paper["sourceId"] == "98765"
    assert paper["canonicalId"] == "10.1234/core-test"


def test_core_paper_without_doi_is_marked_not_portable_for_expansion() -> None:
    """CORE-native fallback IDs must not be presented as expansion-safe."""
    paper = server.CoreApiClient()._result_to_paper(
        {
            "id": 11111,
            "title": "CORE No-DOI Paper",
            "downloadUrl": "https://core.ac.uk/download/pdf/11111.pdf",
        }
    )

    assert paper is not None
    assert paper["source"] == "core"
    assert paper["sourceId"] == "11111"
    assert paper["canonicalId"] == "11111"
    assert paper["expansionIdStatus"] == "not_portable"
    assert paper["recommendedExpansionId"] is None


@pytest.mark.asyncio
async def test_core_search_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    class CapturingAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url: str, **kwargs):
            captured.append({"url": url, **kwargs})
            return DummyResponse(
                status_code=200,
                payload={
                    "total_hits": 1,
                    "results": [
                        {
                            "id": "core-redirect",
                            "title": "Redirect-safe CORE result",
                            "downloadUrl": "https://example.com/paper.pdf",
                        }
                    ],
                },
            )

    monkeypatch.setattr(
        server.httpx,
        "AsyncClient",
        lambda timeout: CapturingAsyncClient(),
    )

    result = await server.CoreApiClient().search("transformers")

    assert result["entries"][0]["paperId"] == "core-redirect"
    assert captured[0]["follow_redirects"] is True


@pytest.mark.asyncio
async def test_core_search_retries_transient_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        DummyResponse(status_code=500, payload={"message": "temporary failure"}),
        DummyResponse(
            status_code=200,
            payload={
                "total_hits": 1,
                "results": [
                    {
                        "id": "core-retry",
                        "title": "Recovered CORE result",
                        "downloadUrl": "https://example.com/recovered.pdf",
                    }
                ],
            },
        ),
    ]
    sleep_calls: list[float] = []

    class RetryAsyncClient:
        def __init__(self, queued_responses: list[DummyResponse]) -> None:
            self._responses = queued_responses
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url: str, **kwargs):
            response = self._responses[self.calls]
            self.calls += 1
            return response

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    retry_client = RetryAsyncClient(responses)
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: retry_client)
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    result = await server.CoreApiClient().search("transformers")

    assert retry_client.calls == 2
    assert sleep_calls == [0.5]
    assert result["entries"][0]["paperId"] == "core-retry"
