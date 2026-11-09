import unittest
from unittest.mock import patch
from src import research


class ResearchTests(unittest.TestCase):
    @patch("src.research._get_json")
    def test_openalex_maps_bibliographic_metadata(self, get_json):
        get_json.return_value = {"results": [{
            "id": "https://openalex.org/W1", "doi": "https://doi.org/10/test",
            "title": "A historical study", "publication_year": 1900, "type": "article",
            "authorships": [{"author": {"display_name": "A. Historian"}}],
            "primary_location": {"landing_page_url": "https://journal.example.org/paper",
                                 "source": {"display_name": "History Journal"}}
        }]}
        rows = research.search_openalex("test", 1)
        self.assertEqual(rows[0]["title"], "A historical study")
        self.assertEqual(rows[0]["publication"], "History Journal")
        self.assertTrue(rows[0]["discovery_only"])

    @patch("src.research.search_library_of_congress", return_value=[])
    @patch("src.research.search_crossref", return_value=[])
    @patch("src.research.search_openalex", return_value=[{
        "title": "Same record", "url": "https://example.org/a", "doi": None
    }])
    def test_discovery_deduplicates_and_never_approves(self, openalex, crossref):
        result = research.discover("history", 5)
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["review_status"], "UNREVIEWED")
        self.assertTrue(result["sources"][0]["source_id"].startswith("src_"))


if __name__ == "__main__":
    unittest.main()
