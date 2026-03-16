import xml.etree.ElementTree as ET

from scholar_search_mcp import server


def test_arxiv_id_from_url_strips_version_suffix() -> None:
    assert (
        server._arxiv_id_from_url("https://arxiv.org/abs/2201.00978v1") == "2201.00978"
    )


def test_text_returns_empty_string_for_missing_element() -> None:
    assert server._text(None) == ""


def test_arxiv_entry_to_paper_extracts_expected_fields() -> None:
    entry = ET.fromstring(
        """
        <entry xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <id>http://arxiv.org/abs/2201.00978v2</id>
          <title> Sample Title </title>
          <summary> Sample abstract </summary>
          <published>2024-01-15T00:00:00Z</published>
          <author><name>Author One</name></author>
          <link rel="alternate" href="https://arxiv.org/abs/2201.00978v2" />
                    <link
                        rel="related"
                        title="pdf"
                        href="https://arxiv.org/pdf/2201.00978v2.pdf"
                    />
          <arxiv:primary_category term="cs.AI" />
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
    """arXiv papers must expose portable provenance and expansion fields."""
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
    assert paper["recommendedExpansionId"] == "2305.12345"
    assert paper["expansionIdStatus"] == "portable"
