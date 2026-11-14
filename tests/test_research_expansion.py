"""Tests for deterministic query expansion, provider toggles, and date windows."""
import unittest
from unittest.mock import patch

from src import research


class ResearchExpansionTests(unittest.TestCase):
    CONFIG = {
        "research_synonyms": [
            {"term": "void", "synonyms": "cavity;chamber"},
            {"term": "pyramid", "synonyms": "Khufu;Giza"},
        ],
        "research_providers": ["OpenAlex"],
        "research_date_window_years": 100,
        "research_max_results": 8,
        "research_relevance_threshold": 40,
    }

    def test_expand_query_adds_only_configured_synonyms(self):
        self.assertEqual(
            research.expand_query("Great Pyramid void", self.CONFIG),
            "Great Pyramid void cavity chamber Khufu Giza"
        )

    @patch("src.research.search_openalex", return_value=[])
    @patch("src.research.search_crossref")
    @patch("src.research.search_library_of_congress")
    @patch("src.research.search_internet_archive")
    def test_provider_toggles_skip_disabled_providers(self, ia, loc, crossref, openalex):
        research.discover("Great Pyramid void", 20, self.CONFIG)
        openalex.assert_called_once_with("Great Pyramid void cavity chamber Khufu Giza", 8)
        crossref.assert_not_called()
        loc.assert_not_called()
        ia.assert_not_called()

    def test_provider_query_variants_are_distinct_and_topic_preserving(self):
        variants = research.provider_query_variants("Great Pyramid void", self.CONFIG)
        self.assertIn("Great Pyramid void", variants["OpenAlex"])
        self.assertNotEqual(variants["OpenAlex"], variants["Crossref"])
        self.assertIn("title:(", variants["Internet Archive"])
        self.assertIn("Library of Congress", variants)

    def test_date_window_keeps_archival_and_undated_records(self):
        self.assertFalse(research._within_date_window({
            "source_type": "academic", "publication_year": 1800
        }, 1926))
        self.assertTrue(research._within_date_window({
            "source_type": "archival", "publication_year": 1800
        }, 1926))
        self.assertTrue(research._within_date_window({
            "source_type": "academic", "publication_year": None
        }, 1926))


if __name__ == "__main__":
    unittest.main()
