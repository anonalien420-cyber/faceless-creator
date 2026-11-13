"""Fixture-based tests for the evidence-engine credibility fixes.

No network access: all provider responses are fixtures. Covers DOI
dedup (OpenAlex URL form vs Crossref bare form), title normalization,
source_type assignment, relevance ranking/filtering, and the
verification needs_review flag for high scores with no primary source.
"""
import unittest
from unittest.mock import patch

from src import research
from src.relevance import (
    DEFAULT_THRESHOLD, abstract_text, filter_sources, score_source,
)
from src.verification import verify_ledger

QUERY = "Great Pyramid ScanPyramids void"

# 2017 ScanPyramids Nature paper, as OpenAlex returns it (DOI as URL).
NATURE_OPENALEX = {
    "provider": "OpenAlex",
    "title": "Discovery of a big void in Khufu\u2019s Pyramid by observation of cosmic-ray muons",
    "url": "https://www.nature.com/articles/nature24647",
    "doi": "https://doi.org/10.1038/nature24647",
    "publication_year": 2017,
    "publication": "Nature",
    "authors": ["Kunihiro Morishima"],
    "work_type": "article",
    "abstract_inverted_index": {
        "discovery": [0], "of": [1, 10], "a": [2], "big": [3], "void": [4],
        "in": [5], "khufu": [6], "pyramid": [7], "by": [8],
        "observation": [9], "cosmic-ray": [11], "muons": [12],
        "scanpyramids": [13], "great": [14],
    },
    "discovery_only": True,
}

# Same paper, as Crossref returns it (DOI bare).
NATURE_CROSSREF = {
    "provider": "Crossref",
    "title": "Discovery of a big void in Khufu\u2019s Pyramid by observation of cosmic-ray muons",
    "url": "https://doi.org/10.1038/nature24647",
    "doi": "10.1038/nature24647",
    "publication_year": 2017,
    "publication": "Nature",
    "authors": ["Kunihiro Morishima"],
    "work_type": "journal-article",
    "discovery_only": True,
}

ARCHAEOACOUSTICS = {
    "provider": "Crossref",
    "title": "Pyramid Tracks: Composing with the Archaeoacoustics of the Great Pyramid",
    "url": "https://doi.org/10.14236/ewic/eva2026.40",
    "doi": "10.14236/ewic/eva2026.40",
    "publication_year": 2026,
    "publication": "Electronic Visualisation and the Arts",
    "authors": ["A. Composer"],
    "work_type": "proceedings-article",
    "discovery_only": True,
}

ON_THE_PYRAMID = {
    "provider": "Crossref",
    "title": "On the Great Pyramid",
    "url": "https://doi.org/10.5743/cairo/9789774168253.003.0003",
    "doi": "10.5743/cairo/9789774168253.003.0003",
    "publication_year": 2010,
    "publication": "Journal of Egyptian Archaeology",
    "authors": ["A. Egyptologist"],
    "work_type": "book-chapter",
    "discovery_only": True,
}

IRRELEVANT = {
    "provider": "Crossref",
    "title": "Cooking with Pyramids: A Chef\u2019s Guide to Layered Desserts",
    "url": "https://doi.org/10.9999/cooking.pyramids",
    "doi": "10.9999/cooking.pyramids",
    "publication_year": 2023,
    "publication": "Culinary Monthly",
    "authors": ["A. Chef"],
    "work_type": "journal-article",
    "discovery_only": True,
}


class DoiNormalizationTests(unittest.TestCase):
    def test_normalize_doi_forms(self):
        self.assertEqual(research.normalize_doi("https://doi.org/10.1038/nature24647"),
                         "10.1038/nature24647")
        self.assertEqual(research.normalize_doi("http://doi.org/10.1038/nature24647"),
                         "10.1038/nature24647")
        self.assertEqual(research.normalize_doi("10.1038/nature24647"),
                         "10.1038/nature24647")
        self.assertEqual(research.normalize_doi("DOI:10.1038/NATURE24647"),
                         "10.1038/nature24647")
        self.assertEqual(research.normalize_doi("  https://doi.org/10.1038/nature24647 "),
                         "10.1038/nature24647")
        self.assertEqual(research.normalize_doi(None), "")
        self.assertEqual(research.normalize_doi(""), "")

    def test_title_normalization(self):
        self.assertEqual(research.normalize_title("Discovery of a Big Void!"),
                         "discovery of a big void")
        self.assertEqual(research.normalize_title("Discovery   of\ta Big Void."),
                         "discovery of a big void")

    @patch("src.research.search_internet_archive", return_value=[])
    @patch("src.research.search_library_of_congress", return_value=[])
    @patch("src.research.search_crossref", return_value=[dict(NATURE_CROSSREF)])
    @patch("src.research.search_openalex", return_value=[dict(NATURE_OPENALEX)])
    def test_openalex_crossref_pair_collapses_to_one(self, *_):
        result = research.discover(QUERY, 10)
        self.assertEqual(len(result["sources"]), 1)
        kept = result["sources"][0]
        self.assertEqual(research.normalize_doi(kept["doi"]), "10.1038/nature24647")
        self.assertEqual(kept["review_status"], "UNREVIEWED")

    @patch("src.research.search_internet_archive", return_value=[])
    @patch("src.research.search_library_of_congress", return_value=[])
    @patch("src.research.search_crossref", return_value=[{
        "provider": "Crossref", "title": "Discovery of a big void!",
        "url": "https://example.org/b", "doi": None,
        "publication_year": 2017, "publication": "Nature Journal"}])
    @patch("src.research.search_openalex", return_value=[{
        "provider": "OpenAlex", "title": "DISCOVERY OF A BIG VOID",
        "url": "https://example.org/a", "doi": None,
        "publication_year": 2017, "publication": "Nature Journal"}])
    def test_title_normalization_dedups_without_doi(self, *_):
        result = research.discover(QUERY, 10)
        self.assertEqual(len(result["sources"]), 1)


class SourceTypeTests(unittest.TestCase):
    def test_assign_source_type_per_provider(self):
        loc = {"provider": "Library of Congress", "source_priority": "institutional_or_primary"}
        self.assertEqual(research.assign_source_type(loc), "archival")
        ia = {"provider": "Internet Archive", "source_priority": "institutional_or_primary"}
        self.assertEqual(research.assign_source_type(ia), "archival")
        journal = {"provider": "OpenAlex", "source_priority": "academic_publication"}
        self.assertEqual(research.assign_source_type(journal), "academic")
        gov = {"provider": "Crossref", "source_priority": "institutional_or_primary"}
        self.assertEqual(research.assign_source_type(gov), "institutional")
        unknown = {"provider": "Crossref", "source_priority": "scholarly_candidate"}
        self.assertEqual(research.assign_source_type(unknown), "other")
        # Discovery never promotes a candidate to primary/official_record.
        for row in (loc, ia, journal, gov, unknown):
            self.assertNotIn(research.assign_source_type(row),
                             ("primary", "official_record"))

    @patch("src.research.search_internet_archive", return_value=[])
    @patch("src.research.search_library_of_congress", return_value=[{
        "provider": "Library of Congress", "title": "Great Pyramid survey photographs",
        "url": "https://www.loc.gov/item/123/", "doi": None,
        "publication_year": "1920", "publication": "Library of Congress catalogue",
        "authors": [], "work_type": "primary-source catalogue record"}])
    @patch("src.research.search_crossref", return_value=[])
    @patch("src.research.search_openalex", return_value=[])
    def test_discover_assigns_archival_to_loc_records(self, *_):
        result = research.discover(QUERY, 10)
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["source_type"], "archival")
        # Archival counts toward the verification +20 primary component.
        ledger = {"sources": [dict(result["sources"][0], source_id="s1",
                                   review_status="APPROVED", notes="Catalogue record")],
                  "claims": [{"claim_id": "c1", "status": "KNOWN", "source_ids": ["s1"]}]}
        report = verify_ledger(ledger)
        self.assertEqual(report["claims"][0]["primary_source_count"], 1)


class RelevanceTests(unittest.TestCase):
    def test_abstract_reconstructed_from_inverted_index(self):
        text = abstract_text(NATURE_OPENALEX)
        self.assertIn("scanpyramids", text)
        self.assertIn("great", text)
        self.assertTrue(text.startswith("discovery of a big void"))

    def test_nature_paper_ranks_first(self):
        fixtures = [dict(ARCHAEOACOUSTICS, source_type="academic"),
                    dict(ON_THE_PYRAMID, source_type="academic"),
                    dict(NATURE_OPENALEX, source_type="academic")]
        scored = sorted(((score_source(f, QUERY)["score"], f["title"]) for f in fixtures),
                        reverse=True)
        self.assertEqual(scored[0][1], NATURE_OPENALEX["title"])
        self.assertEqual(scored[0][0], 80)
        # Both runners-up match two of four query terms (30 + 20 + 15).
        self.assertEqual(scored[1][0], 65)
        self.assertEqual(scored[2][0], 65)
        nature = score_source(dict(NATURE_OPENALEX, source_type="academic"), QUERY)
        self.assertEqual(nature["score"], 80)

    def test_threshold_default_is_40(self):
        self.assertEqual(DEFAULT_THRESHOLD, 40)

    def test_threshold_filtering_logs_drop_reasons(self):
        fixtures = [dict(NATURE_CROSSREF, source_type="academic"),
                    dict(IRRELEVANT, source_type="other")]
        kept, dropped = filter_sources(fixtures, QUERY)
        self.assertEqual([k["title"] for k in kept], [NATURE_CROSSREF["title"]])
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["source"]["title"], IRRELEVANT["title"])
        self.assertLess(dropped[0]["relevance_score"], DEFAULT_THRESHOLD)
        self.assertIn("low_term_overlap", dropped[0]["reasons"])

    def test_unscorable_source_is_kept_for_human_review(self):
        kept, dropped = filter_sources(
            [{"title": "Same record", "url": "https://example.org/a", "doi": None}],
            "history")
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])
        self.assertIsNone(kept[0]["relevance_score"])
        self.assertIn("insufficient_metadata_for_relevance_scoring",
                      kept[0]["relevance_reasons"])

    @patch("src.research.search_internet_archive", return_value=[])
    @patch("src.research.search_library_of_congress", return_value=[])
    @patch("src.research.search_crossref",
           return_value=[dict(NATURE_CROSSREF), dict(IRRELEVANT)])
    @patch("src.research.search_openalex", return_value=[dict(NATURE_OPENALEX)])
    def test_discover_wires_relevance_filter_and_keeps_audit_trail(self, *_):
        result = research.discover(QUERY, 10)
        titles = [s["title"] for s in result["sources"]]
        self.assertIn(NATURE_CROSSREF["title"], titles)
        self.assertNotIn(IRRELEVANT["title"], titles)
        self.assertEqual(len(result["dropped_sources"]), 1)
        self.assertEqual(result["dropped_sources"][0]["source"]["title"],
                         IRRELEVANT["title"])
        self.assertIn("low_term_overlap",
                      result["dropped_sources"][0]["reasons"])
        self.assertEqual(result["relevance_threshold"], DEFAULT_THRESHOLD)
        self.assertTrue(all(s["review_status"] == "UNREVIEWED"
                            for s in result["sources"]))
        self.assertTrue(all("relevance_score" in s for s in result["sources"]))


class VerificationFlagTests(unittest.TestCase):
    def _ledger(self, source_types):
        sources = []
        for i, source_type in enumerate(source_types):
            sources.append({
                "source_id": "s{}".format(i + 1),
                "url": "https://domain{}.example.org/paper".format(i + 1),
                "source_type": source_type, "review_status": "APPROVED",
                "notes": "Human reviewed"})
        return {"sources": sources,
                "claims": [{"claim_id": "c1", "status": "KNOWN",
                            "source_ids": [s["source_id"] for s in sources],
                            "date_start": "2017-11-02"}]}

    def test_high_score_without_primary_source_needs_review(self):
        report = verify_ledger(self._ledger(["academic", "academic"]))
        claim = report["claims"][0]
        self.assertEqual(claim["metadata_completeness_score"], 80)
        self.assertEqual(claim["primary_source_count"], 0)
        self.assertTrue(claim["needs_review"])
        self.assertTrue(any("human review required" in w for w in claim["warnings"]))
        self.assertFalse(report["passed"])
        self.assertTrue(report["needs_review"])

    def test_high_score_with_primary_source_is_not_flagged(self):
        report = verify_ledger(self._ledger(["primary", "academic"]))
        claim = report["claims"][0]
        self.assertEqual(claim["metadata_completeness_score"], 100)
        self.assertEqual(claim["primary_source_count"], 1)
        self.assertFalse(claim["needs_review"])
        self.assertTrue(report["passed"])



    def test_verification_reports_low_relevance_as_warning_only(self):
        ledger = self._ledger(["primary", "academic"])
        ledger["sources"][0]["relevance_score"] = 39
        ledger["sources"][1]["relevance_score"] = 82
        report = verify_ledger(ledger)
        claim = report["claims"][0]
        self.assertEqual(claim["minimum_linked_relevance_score"], 39)
        self.assertEqual(claim["linked_sources_below_relevance_threshold"], 1)
        self.assertEqual(claim["errors"], [])
        self.assertTrue(any("relevance triage threshold" in w for w in claim["warnings"]))
        self.assertEqual(claim["status"], "KNOWN")

if __name__ == "__main__":
    unittest.main()
