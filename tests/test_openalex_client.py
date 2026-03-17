from typing import Any

import pytest

from scholar_search_mcp import server
from tests.helpers import DummyResponse


def test_openalex_work_to_paper_reconstructs_abstract_and_marks_truncation() -> None:
    work = {
        "id": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.1000/example",
        "display_name": "OpenAlex Paper",
        "publication_year": 2024,
        "publication_date": "2024-01-02",
        "authorships": [
            {"author": {"display_name": f"Author {index}"}}
            for index in range(1, 101)
        ],
        "cited_by_count": 42,
        "referenced_works_count": 8,
        "primary_location": {"source": {"display_name": "Nature"}},
        "best_oa_location": {"pdf_url": "https://example.com/paper.pdf"},
        "type": "article",
        "abstract_inverted_index": {
            "OpenAlex": [0],
            "abstract": [1],
            "example": [2],
        },
    }

    paper = server.OpenAlexClient()._work_to_paper(work, include_abstract=True)

    assert paper["paperId"] == "W2741809807"
    assert paper["source"] == "openalex"
    assert paper["sourceId"] == "W2741809807"
    assert paper["canonicalId"] == "10.1000/example"
    assert paper["recommendedExpansionId"] == "10.1000/example"
    assert paper["expansionIdStatus"] == "portable"
    assert paper["abstract"] == "OpenAlex abstract example"
    assert paper["venue"] == "Nature"
    assert paper["pdfUrl"] == "https://example.com/paper.pdf"
    assert paper["authorListTruncated"] is True


@pytest.mark.asyncio
async def test_openalex_search_uses_polite_pool_and_range_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

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
                    "meta": {"count": 1},
                    "results": [
                        {
                            "id": "https://openalex.org/W1",
                            "display_name": "OpenAlex result",
                        }
                    ],
                },
            )

    monkeypatch.setattr(
        server.httpx,
        "AsyncClient",
        lambda timeout: CapturingAsyncClient(),
    )

    result = await server.OpenAlexClient(
        api_key="oa-key",
        mailto="team@example.com",
    ).search("alignment", year="2020-2024")

    assert result["data"][0]["paperId"] == "W1"
    params = captured[0]["params"]
    assert params["api_key"] == "oa-key"
    assert params["mailto"] == "team@example.com"
    assert params["search"] == "alignment"
    assert (
        params["filter"]
        == "from_publication_date:2020-01-01,to_publication_date:2024-12-31"
    )


@pytest.mark.asyncio
async def test_openalex_get_paper_citations_uses_cited_by_api_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        DummyResponse(
            status_code=200,
            payload={
                "id": "https://openalex.org/W1",
                "display_name": "Seed paper",
                "cited_by_api_url": "https://api.openalex.org/works?filter=cites:W1",
            },
        ),
        DummyResponse(
            status_code=200,
            payload={
                "meta": {"count": 1, "next_cursor": "next-cursor"},
                "results": [
                    {
                        "id": "https://openalex.org/W2",
                        "display_name": "Citing paper",
                    }
                ],
            },
        ),
    ]
    captured: list[dict[str, Any]] = []

    class QueueAsyncClient:
        def __init__(self, queued: list[DummyResponse]) -> None:
            self._queued = queued
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url: str, **kwargs):
            captured.append({"url": url, **kwargs})
            response = self._queued[self.calls]
            self.calls += 1
            return response

    queue = QueueAsyncClient(responses)
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: queue)

    result = await server.OpenAlexClient().get_paper_citations("W1", cursor="cursor-*")

    assert result["data"][0]["paperId"] == "W2"
    assert captured[1]["url"] == "https://api.openalex.org/works?filter=cites:W1"
    assert captured[1]["params"]["cursor"] == "cursor-*"
    assert result["pagination"]["nextCursor"] == "next-cursor"


@pytest.mark.asyncio
async def test_openalex_get_paper_references_batches_ids_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        DummyResponse(
            status_code=200,
            payload={
                "id": "https://openalex.org/W1",
                "display_name": "Seed paper",
                "referenced_works": [
                    "https://openalex.org/W10",
                    "https://openalex.org/W20",
                ],
            },
        ),
        DummyResponse(
            status_code=200,
            payload={
                "meta": {"count": 2},
                "results": [
                    {
                        "id": "https://openalex.org/W20",
                        "display_name": "Second reference",
                    },
                    {
                        "id": "https://openalex.org/W10",
                        "display_name": "First reference",
                    },
                ],
            },
        ),
    ]
    captured: list[dict[str, Any]] = []

    class QueueAsyncClient:
        def __init__(self, queued: list[DummyResponse]) -> None:
            self._queued = queued
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url: str, **kwargs):
            captured.append({"url": url, **kwargs})
            response = self._queued[self.calls]
            self.calls += 1
            return response

    queue = QueueAsyncClient(responses)
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda timeout: queue)

    result = await server.OpenAlexClient().get_paper_references("W1", limit=2)

    assert [paper["paperId"] for paper in result["data"]] == ["W10", "W20"]
    assert captured[1]["params"]["filter"] == "openalex:W10|W20"
    assert result["pagination"]["hasMore"] is False
