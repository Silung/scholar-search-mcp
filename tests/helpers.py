import json
from typing import Any


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


def _streamable_http_event_payload(body: str) -> dict[str, Any]:
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line.removeprefix("data: "))
    raise AssertionError(f"No SSE data payload found in response: {body!r}")


class DummySerpApiAsyncClient:
    """Minimal async HTTP client stub for SerpApi tests."""

    def __init__(self, response: DummyResponse) -> None:
        self._response = response

    async def __aenter__(self) -> "DummySerpApiAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, *, params: dict) -> DummyResponse:
        return self._response
