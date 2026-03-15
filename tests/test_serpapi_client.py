import json

import pytest

from scholar_search_mcp import server
from tests.helpers import DummyResponse, DummySerpApiAsyncClient


def test_serpapi_normalize_organic_result_minimal() -> None:
    """Minimal valid organic result should normalize to a Paper dict."""
    from scholar_search_mcp.clients.serpapi.normalize import normalize_organic_result

    result = {
        "title": "Attention Is All You Need",
        "result_id": "abc123",
        "link": "https://arxiv.org/abs/1706.03762",
        "snippet": "A transformer model based on attention mechanisms.",
        "publication_info": {
            "summary": "A Vaswani, N Shazeer - Advances in NeurIPS, 2017",
            "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
        },
        "inline_links": {
            "cited_by": {"total": 80000, "cites_id": "cites-001"},
            "versions": {"cluster_id": "cluster-xyz"},
        },
    }

    paper = normalize_organic_result(result)

    assert paper is not None
    assert paper["title"] == "Attention Is All You Need"
    assert paper["source"] == "serpapi_google_scholar"
    assert paper["sourceId"] == "abc123"
    # canonicalId: DOI not found in URL, so cluster_id > result_id
    assert paper["canonicalId"] == "cluster-xyz"
    assert paper["citationCount"] == 80000
    assert paper["year"] == 2017
    assert len(paper["authors"]) == 2
    assert paper["authors"][0]["name"] == "Ashish Vaswani"
    assert paper["abstract"] == "A transformer model based on attention mechanisms."
    # Scholar extras must be preserved
    assert paper["scholarResultId"] == "abc123"
    assert paper["scholarClusterId"] == "cluster-xyz"
    assert paper["scholarCitesId"] == "cites-001"


def test_serpapi_normalize_extracts_doi_canonical_id() -> None:
    """When a DOI is present in the URL, it should be used as canonicalId."""
    from scholar_search_mcp.clients.serpapi.normalize import normalize_organic_result

    result = {
        "title": "DOI Paper",
        "result_id": "rid-1",
        "link": "https://doi.org/10.1038/s41586-021-03819-2",
        "publication_info": {"summary": "Nature, 2021"},
    }

    paper = normalize_organic_result(result)

    assert paper is not None
    assert paper["canonicalId"] == "10.1038/s41586-021-03819-2"
    assert paper["sourceId"] == "rid-1"


def test_serpapi_normalize_returns_none_for_missing_title() -> None:
    """Results without a title must be silently dropped."""
    from scholar_search_mcp.clients.serpapi.normalize import normalize_organic_result

    assert normalize_organic_result({}) is None
    assert normalize_organic_result({"title": "", "result_id": "x"}) is None


def test_serpapi_normalize_pdf_url_from_resources() -> None:
    """PDF URL should be extracted from the resources list when available."""
    from scholar_search_mcp.clients.serpapi.normalize import normalize_organic_result

    result = {
        "title": "PDF Paper",
        "result_id": "rid-2",
        "link": "https://example.com/paper",
        "resources": [
            {
                "title": "PDF",
                "file_format": "PDF",
                "link": "https://example.com/paper.pdf",
            },
        ],
    }

    paper = normalize_organic_result(result)

    assert paper is not None
    assert paper["pdfUrl"] == "https://example.com/paper.pdf"


def test_serpapi_normalize_year_range_parser() -> None:
    """_parse_year_range must correctly handle all expected input formats."""
    from scholar_search_mcp.clients.serpapi.normalize import _parse_year_range

    assert _parse_year_range("2023") == (2023, 2023)
    assert _parse_year_range("2020-2023") == (2020, 2023)
    assert _parse_year_range("2020-") == (2020, None)
    assert _parse_year_range("-2023") == (None, 2023)
    assert _parse_year_range("invalid") == (None, None)
    # Short strings that are not 4-digit years must not cause errors
    assert _parse_year_range("20") == (None, None)
    assert _parse_year_range("20-23") == (None, None)
    assert _parse_year_range("") == (None, None)


def test_serpapi_normalize_source_id_fallback_chain() -> None:
    """sourceId must follow result_id > cluster_id > cites_id priority."""
    from scholar_search_mcp.clients.serpapi.normalize import normalize_organic_result

    # Only cites_id available
    paper = normalize_organic_result(
        {
            "title": "Fallback paper",
            "inline_links": {"cited_by": {"cites_id": "only-cites-id"}},
        }
    )
    assert paper is not None
    assert paper["sourceId"] == "only-cites-id"

    # cluster_id beats cites_id
    paper2 = normalize_organic_result(
        {
            "title": "Cluster paper",
            "inline_links": {
                "cited_by": {"cites_id": "some-cites"},
                "versions": {"cluster_id": "cluster-wins"},
            },
        }
    )
    assert paper2 is not None
    assert paper2["sourceId"] == "cluster-wins"


@pytest.mark.asyncio
async def test_serpapi_client_raises_key_missing_error_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client must raise SerpApiKeyMissingError immediately if no key is set."""
    from scholar_search_mcp.clients.serpapi import (
        SerpApiKeyMissingError,
        SerpApiScholarClient,
    )

    client = SerpApiScholarClient(api_key=None)

    with pytest.raises(SerpApiKeyMissingError, match="SERPAPI_API_KEY"):
        await client.search("transformers")


@pytest.mark.asyncio
async def test_serpapi_client_raises_quota_error_on_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SerpApiQuotaError must be raised for HTTP 429 responses."""
    from scholar_search_mcp.clients.serpapi import (
        SerpApiQuotaError,
        SerpApiScholarClient,
    )

    dummy = DummySerpApiAsyncClient(
        DummyResponse(status_code=429, headers={"Retry-After": "60"})
    )
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: dummy)

    client = SerpApiScholarClient(api_key="test-key")
    with pytest.raises(SerpApiQuotaError, match="429"):
        await client.search("transformers")


@pytest.mark.asyncio
async def test_serpapi_client_raises_upstream_error_on_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SerpApiUpstreamError must be raised for HTTP 5xx responses."""
    from scholar_search_mcp.clients.serpapi import (
        SerpApiScholarClient,
        SerpApiUpstreamError,
    )

    dummy = DummySerpApiAsyncClient(DummyResponse(status_code=503))
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: dummy)

    client = SerpApiScholarClient(api_key="test-key")
    with pytest.raises(SerpApiUpstreamError, match="503"):
        await client.search("transformers")


@pytest.mark.asyncio
async def test_serpapi_client_raises_key_error_for_application_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application-level SerpApi auth errors must raise SerpApiKeyMissingError."""
    from scholar_search_mcp.clients.serpapi import (
        SerpApiKeyMissingError,
        SerpApiScholarClient,
    )

    dummy = DummySerpApiAsyncClient(
        DummyResponse(status_code=200, payload={"error": "Invalid API key"})
    )
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: dummy)

    client = SerpApiScholarClient(api_key="bad-key")
    with pytest.raises(SerpApiKeyMissingError, match="authentication error"):
        await client.search("transformers")


@pytest.mark.asyncio
async def test_serpapi_client_search_returns_normalized_papers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful SerpApi search must return a list of normalized paper dicts."""
    from scholar_search_mcp.clients.serpapi import SerpApiScholarClient

    serpapi_payload = {
        "organic_results": [
            {
                "title": "Neural Networks Survey",
                "result_id": "r-001",
                "link": "https://example.com/nn-survey",
                "snippet": "A comprehensive survey.",
                "publication_info": {
                    "summary": "A. Smith - IEEE Journal, 2022",
                    "authors": [{"name": "Alice Smith"}],
                },
                "inline_links": {
                    "cited_by": {"total": 100},
                    "versions": {"cluster_id": "cl-001"},
                },
            }
        ]
    }
    dummy = DummySerpApiAsyncClient(
        DummyResponse(status_code=200, payload=serpapi_payload)
    )
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: dummy)

    client = SerpApiScholarClient(api_key="test-key")
    papers = await client.search("neural networks")

    assert len(papers) == 1
    p = papers[0]
    assert p["title"] == "Neural Networks Survey"
    assert p["source"] == "serpapi_google_scholar"
    assert p["sourceId"] == "r-001"
    assert p["year"] == 2022
    assert p["citationCount"] == 100


@pytest.mark.asyncio
async def test_serpapi_client_search_with_year_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Year range should be translated to as_ylo/as_yhi in the request params."""
    from scholar_search_mcp.clients.serpapi import SerpApiScholarClient

    captured_params: list[dict] = []

    class CapturingAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get(self, url: str, *, params: dict) -> DummyResponse:
            captured_params.append(dict(params))
            return DummyResponse(status_code=200, payload={"organic_results": []})

    monkeypatch.setattr(
        server.httpx, "AsyncClient", lambda timeout: CapturingAsyncClient()
    )

    client = SerpApiScholarClient(api_key="test-key")
    await client.search("transformers", year="2020-2023")

    assert len(captured_params) == 1
    p = captured_params[0]
    assert p["as_ylo"] == 2020
    assert p["as_yhi"] == 2023
    assert p["engine"] == "google_scholar"


@pytest.mark.asyncio
async def test_serpapi_client_get_citation_formats_returns_structured_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_citation_formats must return the raw SerpApi response dict."""
    from scholar_search_mcp.clients.serpapi import SerpApiScholarClient

    cite_payload = {
        "citations": [
            {"title": "MLA", "snippet": "Smith, A. (2022)..."},
            {"title": "APA", "snippet": "Smith, A. 2022..."},
        ],
        "links": [
            {"name": "BibTeX", "link": "https://scholar.google.com/bibtex/r-001"},
        ],
    }
    dummy = DummySerpApiAsyncClient(
        DummyResponse(status_code=200, payload=cite_payload)
    )
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: dummy)

    client = SerpApiScholarClient(api_key="test-key")
    result = await client.get_citation_formats("r-001")

    assert result["citations"][0]["title"] == "MLA"
    assert result["links"][0]["name"] == "BibTeX"


@pytest.mark.asyncio
async def test_serpapi_client_get_citation_formats_rejects_empty_result_id() -> None:
    """Empty result_id must raise ValueError before any HTTP call."""
    from scholar_search_mcp.clients.serpapi import SerpApiScholarClient

    client = SerpApiScholarClient(api_key="test-key")

    with pytest.raises(ValueError, match="result_id must not be empty"):
        await client.get_citation_formats("")

    with pytest.raises(ValueError, match="result_id must not be empty"):
        await client.get_citation_formats("   ")


@pytest.mark.asyncio
async def test_search_papers_uses_serpapi_when_enabled_and_others_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SerpApi must be tried between Semantic Scholar and arXiv in the chain."""

    class FailingCoreClient:
        async def search(self, **kwargs) -> dict:
            raise RuntimeError("core unavailable")

    class FailingSemanticClient:
        async def search_papers(self, **kwargs) -> dict:
            raise RuntimeError("ss unavailable")

    class FakeSerpApiClient:
        async def search(self, **kwargs) -> list[dict]:
            return [
                {
                    "title": "SerpApi Result",
                    "paperId": "serpapi-1",
                    "source": "serpapi_google_scholar",
                    "sourceId": "serpapi-1",
                    "canonicalId": "serpapi-1",
                }
            ]

    monkeypatch.setattr(server, "enable_core", True)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "enable_arxiv", True)
    monkeypatch.setattr(server, "core_client", FailingCoreClient())
    monkeypatch.setattr(server, "client", FailingSemanticClient())
    monkeypatch.setattr(server, "serpapi_client", FakeSerpApiClient())

    response = await server.call_tool("search_papers", {"query": "neural nets"})
    payload = json.loads(response[0].text)

    assert payload["total"] == 1
    assert payload["data"][0]["title"] == "SerpApi Result"
    assert payload["brokerMetadata"]["providerUsed"] == "serpapi_google_scholar"
    assert payload["brokerMetadata"]["continuationSupported"] is False


@pytest.mark.asyncio
async def test_search_papers_skips_serpapi_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SerpApi must NOT be used when enable_serpapi is False (the default)."""

    class SerpApiClientSpy:
        def __init__(self) -> None:
            self.called = False

        async def search(self, **kwargs) -> list[dict]:
            self.called = True
            return []

    class FailingSemanticClient:
        async def search_papers(self, **kwargs) -> dict:
            raise RuntimeError("ss unavailable")

    class ArxivFallback:
        async def search(self, **kwargs) -> dict:
            return {
                "totalResults": 1,
                "entries": [
                    {"paperId": "ax-1", "title": "arXiv paper", "source": "arxiv"}
                ],
            }

    serpapi_spy = SerpApiClientSpy()

    monkeypatch.setattr(server, "enable_core", False)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_serpapi", False)  # disabled
    monkeypatch.setattr(server, "enable_arxiv", True)
    monkeypatch.setattr(server, "client", FailingSemanticClient())
    monkeypatch.setattr(server, "serpapi_client", serpapi_spy)
    monkeypatch.setattr(server, "arxiv_client", ArxivFallback())

    await server.call_tool("search_papers", {"query": "test"})

    assert not serpapi_spy.called, "SerpApi must not be called when disabled"


@pytest.mark.asyncio
async def test_search_papers_serpapi_falls_through_to_arxiv_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If SerpApi fails, arXiv fallback must still be tried."""

    class FailingCoreClient:
        async def search(self, **kwargs) -> dict:
            raise RuntimeError("core unavailable")

    class FailingSemanticClient:
        async def search_papers(self, **kwargs) -> dict:
            raise RuntimeError("ss unavailable")

    class FailingSerpApiClient:
        async def search(self, **kwargs) -> list[dict]:
            raise RuntimeError("serpapi unavailable")

    class ArxivFallback:
        async def search(self, **kwargs) -> dict:
            return {
                "totalResults": 1,
                "entries": [
                    {
                        "paperId": "arxiv-2",
                        "title": "arXiv fallback",
                        "source": "arxiv",
                    }
                ],
            }

    monkeypatch.setattr(server, "enable_core", True)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "enable_arxiv", True)
    monkeypatch.setattr(server, "core_client", FailingCoreClient())
    monkeypatch.setattr(server, "client", FailingSemanticClient())
    monkeypatch.setattr(server, "serpapi_client", FailingSerpApiClient())
    monkeypatch.setattr(server, "arxiv_client", ArxivFallback())

    response = await server.call_tool("search_papers", {"query": "fallback"})
    payload = json.loads(response[0].text)

    assert payload["data"][0]["paperId"] == "arxiv-2"
    assert payload["brokerMetadata"]["providerUsed"] == "arxiv"


@pytest.mark.asyncio
async def test_search_papers_skips_serpapi_for_ss_only_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SerpApi must be bypassed when SS-only filters are present."""

    class SerpApiClientSpy:
        def __init__(self) -> None:
            self.called = False

        async def search(self, **kwargs) -> list[dict]:
            self.called = True
            return []

    class SemanticClient:
        async def search_papers(self, **kwargs) -> dict:
            return {"total": 1, "offset": 0, "data": [{"paperId": "s2-1"}]}

    serpapi_spy = SerpApiClientSpy()

    monkeypatch.setattr(server, "enable_core", False)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "enable_arxiv", False)
    monkeypatch.setattr(server, "client", SemanticClient())
    monkeypatch.setattr(server, "serpapi_client", serpapi_spy)

    await server.call_tool(
        "search_papers",
        {"query": "test", "fieldsOfStudy": "Computer Science"},
    )

    assert not serpapi_spy.called, "SerpApi must be skipped for SS-only filters"


@pytest.mark.asyncio
async def test_search_papers_serpapi_broker_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """brokerMetadata must identify SerpApi and set continuationSupported=false."""

    class FakeSerpApiClient:
        async def search(self, **kwargs) -> list[dict]:
            return [
                {
                    "title": "Scholar Paper",
                    "paperId": "sp-1",
                    "source": "serpapi_google_scholar",
                    "sourceId": "sp-1",
                    "canonicalId": "sp-1",
                }
            ]

    monkeypatch.setattr(server, "enable_core", False)
    monkeypatch.setattr(server, "enable_semantic_scholar", False)
    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "enable_arxiv", False)
    monkeypatch.setattr(server, "serpapi_client", FakeSerpApiClient())

    response = await server.call_tool("search_papers", {"query": "scholar"})
    payload = json.loads(response[0].text)

    bm = payload["brokerMetadata"]
    assert bm["mode"] == "brokered_single_page"
    assert bm["providerUsed"] == "serpapi_google_scholar"
    assert bm["continuationSupported"] is False


def test_serpapi_paper_provenance_fields_correct() -> None:
    """SerpApi results must carry source, sourceId, canonicalId."""
    from scholar_search_mcp.clients.serpapi.normalize import normalize_organic_result

    result = {
        "title": "Provenance Test Paper",
        "result_id": "prov-001",
        "link": "https://doi.org/10.1234/provtest",
        "publication_info": {"summary": "Some Journal, 2021"},
    }

    paper = normalize_organic_result(result)

    assert paper is not None
    assert paper["source"] == "serpapi_google_scholar"
    assert paper["sourceId"] == "prov-001"
    assert paper["canonicalId"] == "10.1234/provtest"


def test_serpapi_paper_canonical_id_falls_back_to_cluster_id() -> None:
    """When no DOI is available, cluster_id is the canonicalId."""
    from scholar_search_mcp.clients.serpapi.normalize import normalize_organic_result

    result = {
        "title": "No DOI Paper",
        "result_id": "no-doi-001",
        "link": "https://example.com/nodoi",
        "inline_links": {"versions": {"cluster_id": "cluster-abc"}},
    }

    paper = normalize_organic_result(result)

    assert paper is not None
    assert paper["canonicalId"] == "cluster-abc"
    assert paper["sourceId"] == "no-doi-001"


@pytest.mark.asyncio
async def test_call_tool_get_citation_formats_requires_serpapi_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_paper_citation_formats must raise when SerpApi is disabled."""
    monkeypatch.setattr(server, "enable_serpapi", False)

    with pytest.raises(ValueError, match="SCHOLAR_SEARCH_ENABLE_SERPAPI"):
        await server.call_tool("get_paper_citation_formats", {"result_id": "abc123"})


@pytest.mark.asyncio
async def test_call_tool_get_citation_formats_returns_normalized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_paper_citation_formats must return a normalized CitationFormatsResponse."""

    class FakeSerpApiClient:
        async def get_citation_formats(self, result_id: str) -> dict:
            return {
                "citations": [
                    {"title": "MLA", "snippet": "Vaswani, A. et al. 2017..."},
                    {"title": "APA", "snippet": "Vaswani, A. (2017)..."},
                ],
                "links": [
                    {
                        "name": "BibTeX",
                        "link": "https://scholar.google.com/bibtex/attn",
                    },
                    {
                        "name": "EndNote",
                        "link": "https://scholar.google.com/endnote/attn",
                    },
                ],
            }

    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "serpapi_client", FakeSerpApiClient())

    response = await server.call_tool(
        "get_paper_citation_formats", {"result_id": "attn-001"}
    )
    payload = json.loads(response[0].text)

    assert payload["resultId"] == "attn-001"
    assert payload["provider"] == "serpapi_google_scholar"
    assert len(payload["citations"]) == 2
    assert payload["citations"][0]["title"] == "MLA"
    assert len(payload["exportLinks"]) == 2
    assert payload["exportLinks"][0]["name"] == "BibTeX"


@pytest.mark.asyncio
async def test_call_tool_get_citation_formats_propagates_key_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SerpApiKeyMissingError from the client must propagate through dispatch."""
    from scholar_search_mcp.clients.serpapi import (
        SerpApiKeyMissingError,
        SerpApiScholarClient,
    )

    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "serpapi_client", SerpApiScholarClient(api_key=None))

    with pytest.raises(SerpApiKeyMissingError, match="SERPAPI_API_KEY"):
        await server.call_tool("get_paper_citation_formats", {"result_id": "abc123"})


@pytest.mark.asyncio
async def test_search_papers_raises_when_serpapi_enabled_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SerpApiKeyMissingError must propagate from search_papers, not fall back.

    When SerpApi is enabled but misconfigured (no key), the caller must receive
    an actionable error rather than silently getting arXiv results that the
    agent cannot correlate with the configured provider.
    """
    from scholar_search_mcp.clients.serpapi import (
        SerpApiKeyMissingError,
        SerpApiScholarClient,
    )

    class FailingCoreClient:
        async def search(self, **kwargs) -> dict:
            raise RuntimeError("core unavailable")

    class FailingSemanticClient:
        async def search_papers(self, **kwargs) -> dict:
            raise RuntimeError("ss unavailable")

    class ArxivFallback:
        async def search(self, **kwargs) -> dict:
            return {
                "totalResults": 1,
                "entries": [{"paperId": "ax-should-not-reach"}],
            }

    monkeypatch.setattr(server, "enable_core", True)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "enable_arxiv", True)
    monkeypatch.setattr(server, "core_client", FailingCoreClient())
    monkeypatch.setattr(server, "client", FailingSemanticClient())
    # A real client with no key — will raise SerpApiKeyMissingError on search()
    monkeypatch.setattr(server, "serpapi_client", SerpApiScholarClient(api_key=None))
    monkeypatch.setattr(server, "arxiv_client", ArxivFallback())

    with pytest.raises(SerpApiKeyMissingError, match="SERPAPI_API_KEY"):
        await server.call_tool("search_papers", {"query": "test"})


@pytest.mark.asyncio
async def test_search_papers_serpapi_transient_error_still_falls_back_to_arxiv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient SerpApi failures (network/5xx) must still fall back to arXiv.

    Only config/auth errors should bubble; all other failures continue the
    normal fallback chain.
    """
    from scholar_search_mcp.clients.serpapi import (
        SerpApiUpstreamError,
    )

    class FailingCoreClient:
        async def search(self, **kwargs) -> dict:
            raise RuntimeError("core unavailable")

    class FailingSemanticClient:
        async def search_papers(self, **kwargs) -> dict:
            raise RuntimeError("ss unavailable")

    class TransientSerpApiClient:
        async def search(self, **kwargs) -> list[dict]:
            raise SerpApiUpstreamError("HTTP 503 transient")

    class ArxivFallback:
        async def search(self, **kwargs) -> dict:
            return {
                "totalResults": 1,
                "entries": [{"paperId": "ax-transient", "source": "arxiv"}],
            }

    monkeypatch.setattr(server, "enable_core", True)
    monkeypatch.setattr(server, "enable_semantic_scholar", True)
    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "enable_arxiv", True)
    monkeypatch.setattr(server, "core_client", FailingCoreClient())
    monkeypatch.setattr(server, "client", FailingSemanticClient())
    monkeypatch.setattr(server, "serpapi_client", TransientSerpApiClient())
    monkeypatch.setattr(server, "arxiv_client", ArxivFallback())

    response = await server.call_tool("search_papers", {"query": "transient"})
    payload = json.loads(response[0].text)

    assert payload["data"][0]["paperId"] == "ax-transient"
    assert payload["brokerMetadata"]["providerUsed"] == "arxiv"


def test_serpapi_normalize_scholar_result_id_preserved_as_extra() -> None:
    """scholarResultId extra must always be the raw result_id, never cluster_id."""
    from scholar_search_mcp.clients.serpapi.normalize import normalize_organic_result

    # result_id present: scholarResultId == result_id, sourceId == result_id
    paper = normalize_organic_result(
        {
            "title": "Result ID Paper",
            "result_id": "rid-100",
            "inline_links": {"versions": {"cluster_id": "cid-100"}},
        }
    )
    assert paper is not None
    assert paper["scholarResultId"] == "rid-100"
    assert paper["sourceId"] == "rid-100"  # result_id wins in sourceId priority
    assert paper["scholarClusterId"] == "cid-100"

    # result_id absent: sourceId falls back to cluster_id; scholarResultId is None
    paper2 = normalize_organic_result(
        {
            "title": "Cluster Only Paper",
            "inline_links": {"versions": {"cluster_id": "cid-only"}},
        }
    )
    assert paper2 is not None
    assert paper2["sourceId"] == "cid-only"
    assert paper2["scholarResultId"] is None  # no result_id: field present but None


def test_serpapi_normalize_source_id_not_same_as_result_id_when_absent() -> None:
    """sourceId diverges from result_id when only cluster_id or cites_id exists.

    This confirms the contract: agents MUST use scholarResultId (not sourceId)
    when calling get_paper_citation_formats.
    """
    from scholar_search_mcp.clients.serpapi.normalize import normalize_organic_result

    paper = normalize_organic_result(
        {
            "title": "Cites ID Only Paper",
            "inline_links": {"cited_by": {"cites_id": "cites-999", "total": 5}},
        }
    )
    assert paper is not None
    # sourceId falls back to cites_id — NOT a result_id
    assert paper["sourceId"] == "cites-999"
    # No result_id => scholarResultId field is None (not absent)
    assert paper["scholarResultId"] is None


@pytest.mark.asyncio
async def test_call_tool_get_citation_formats_routes_to_serpapi_client_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """call_tool must route get_paper_citation_formats to
    serpapi_client.get_citation_formats.

    This is the routing-spy analog of test_call_tool_routes_non_search_tools for
    the SerpApi-backed citation tool — verifying that dispatch correctly calls
    the right client method with the correct arguments.
    """

    class RecordingSerpApiClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def get_citation_formats(self, result_id: str) -> dict:
            self.calls.append(("get_citation_formats", {"result_id": result_id}))
            return {
                "citations": [{"title": "MLA", "snippet": "Smith, A. 2023."}],
                "links": [
                    {"name": "BibTeX", "link": "https://scholar.google.com/bib/x"}
                ],
            }

    spy = RecordingSerpApiClient()
    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "serpapi_client", spy)

    await server.call_tool("get_paper_citation_formats", {"result_id": "route-spy-001"})

    assert spy.calls == [("get_citation_formats", {"result_id": "route-spy-001"})], (
        f"Unexpected calls: {spy.calls}"
    )


@pytest.mark.asyncio
async def test_search_papers_serpapi_all_provenance_fields_in_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All provenance fields must survive the full call_tool('search_papers') pipeline.

    Verifies that source, sourceId, canonicalId, scholarResultId, scholarClusterId,
    and scholarCitesId are all present in the call_tool response when SerpApi is the
    provider — not just in normalize_organic_result unit tests.
    """
    from scholar_search_mcp.clients.serpapi.normalize import normalize_organic_result

    # Build a normalized result the same way the real client does
    normalized = normalize_organic_result(
        {
            "title": "End-to-End Provenance Paper",
            "result_id": "e2e-rid-001",
            "link": "https://doi.org/10.9999/e2e",
            "snippet": "Snippet text.",
            "publication_info": {
                "summary": "E2E Journal, 2023",
                "authors": [{"name": "First Author"}, {"name": "Second Author"}],
            },
            "inline_links": {
                "cited_by": {"total": 25, "cites_id": "cites-e2e"},
                "versions": {"cluster_id": "cluster-e2e"},
            },
        }
    )
    assert normalized is not None  # guard so test failure is obvious

    normalized_paper: dict[str, object] = normalized

    class FakeSerpApiClient:
        async def search(self, **kwargs) -> list[dict]:
            return [normalized_paper]

    monkeypatch.setattr(server, "enable_core", False)
    monkeypatch.setattr(server, "enable_semantic_scholar", False)
    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "enable_arxiv", False)
    monkeypatch.setattr(server, "serpapi_client", FakeSerpApiClient())

    response = await server.call_tool("search_papers", {"query": "e2e provenance"})
    payload = json.loads(response[0].text)

    assert len(payload["data"]) == 1
    paper = payload["data"][0]

    # Provider identity
    assert paper["source"] == "serpapi_google_scholar"
    # sourceId: result_id wins in priority
    assert paper["sourceId"] == "e2e-rid-001"
    # canonicalId: DOI wins in priority
    assert paper["canonicalId"] == "10.9999/e2e"
    # Scholar extras preserved for follow-up tools
    assert paper["scholarResultId"] == "e2e-rid-001"
    assert paper["scholarClusterId"] == "cluster-e2e"
    assert paper["scholarCitesId"] == "cites-e2e"
    # Broker metadata
    assert payload["brokerMetadata"]["providerUsed"] == "serpapi_google_scholar"
    assert payload["brokerMetadata"]["continuationSupported"] is False


@pytest.mark.asyncio
async def test_search_papers_serpapi_empty_results_fall_through_to_arxiv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When SerpApi returns an empty list, search_papers must try arXiv next.

    Distinct from transient errors: the client succeeds but returns no papers.
    The fallback chain must continue as if SerpApi was not available.
    """

    class EmptySerpApiClient:
        async def search(self, **kwargs) -> list[dict]:
            return []

    class ArxivFallback:
        async def search(self, **kwargs) -> dict:
            return {
                "totalResults": 1,
                "entries": [
                    {
                        "paperId": "ax-empty-fallback",
                        "title": "arXiv fallback",
                        "source": "arxiv",
                    }
                ],
            }

    monkeypatch.setattr(server, "enable_core", False)
    monkeypatch.setattr(server, "enable_semantic_scholar", False)
    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "enable_arxiv", True)
    monkeypatch.setattr(server, "serpapi_client", EmptySerpApiClient())
    monkeypatch.setattr(server, "arxiv_client", ArxivFallback())

    response = await server.call_tool("search_papers", {"query": "empty results"})
    payload = json.loads(response[0].text)

    assert payload["data"][0]["paperId"] == "ax-empty-fallback"
    assert payload["brokerMetadata"]["providerUsed"] == "arxiv"


@pytest.mark.asyncio
async def test_search_papers_serpapi_quota_error_falls_back_to_arxiv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SerpApiQuotaError (HTTP 429) must be treated as transient and fall back to arXiv.

    Quota exhaustion is a transient operational state, not a config/auth error;
    arXiv must still be tried so the user gets useful results.
    """
    from scholar_search_mcp.clients.serpapi import SerpApiQuotaError

    class QuotaSerpApiClient:
        async def search(self, **kwargs) -> list[dict]:
            raise SerpApiQuotaError("HTTP 429: quota exhausted")

    class ArxivFallback:
        async def search(self, **kwargs) -> dict:
            return {
                "totalResults": 1,
                "entries": [
                    {
                        "paperId": "ax-quota-fallback",
                        "title": "arXiv result",
                        "source": "arxiv",
                    }
                ],
            }

    monkeypatch.setattr(server, "enable_core", False)
    monkeypatch.setattr(server, "enable_semantic_scholar", False)
    monkeypatch.setattr(server, "enable_serpapi", True)
    monkeypatch.setattr(server, "enable_arxiv", True)
    monkeypatch.setattr(server, "serpapi_client", QuotaSerpApiClient())
    monkeypatch.setattr(server, "arxiv_client", ArxivFallback())

    response = await server.call_tool("search_papers", {"query": "quota"})
    payload = json.loads(response[0].text)

    assert payload["data"][0]["paperId"] == "ax-quota-fallback"
    assert payload["brokerMetadata"]["providerUsed"] == "arxiv"
