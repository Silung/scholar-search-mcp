import xml.etree.ElementTree as ET

import pytest

from scholar_search_mcp import server


def test_arxiv_id_from_url_strips_version_suffix() -> None:
    assert (
        server._arxiv_id_from_url("https://arxiv.org/abs/2201.00978v1") == "2201.00978"
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
        "sourceId": "42",
        "canonicalId": "10.1000/example-doi",
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


def test_arxiv_paper_has_provenance_fields() -> None:
    """arXiv papers must expose source, sourceId, and canonicalId."""
    entry = ET.fromstring(
        """
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:arxiv="http://arxiv.org/schemas/atom">
          <id>http://arxiv.org/abs/2305.12345v1</id>
          <title>Provenance Test Paper</title>
          <summary>Abstract text.</summary>
          <published>2023-05-01T00:00:00Z</published>
          <author><name>Jane Doe</name></author>
          <link rel="alternate" href="https://arxiv.org/abs/2305.12345v1" />
          <arxiv:primary_category term="cs.LG" />
        </entry>
        """
    )
    paper = server.ArxivClient()._entry_to_paper(entry)

    assert paper is not None
    assert paper["source"] == "arxiv"
    assert paper["sourceId"] == "2305.12345"
    assert paper["canonicalId"] == "2305.12345"


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


def test_core_paper_canonical_id_falls_back_to_source_id_without_doi() -> None:
    """CORE papers without a DOI must use the CORE native ID as canonicalId."""
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
