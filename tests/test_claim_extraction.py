"""No-invention and provenance tests for candidate claim extraction."""
import unittest

from src.claim_extraction import extract_claims


class ClaimExtractionTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "source_id": "nature-2017",
            "title": "Discovery of a big void in Khufu's Pyramid",
            "url": "https://example.org/nature-record",
            "publication_year": 2017,
            "source_type": "academic",
            "abstract": (
                "Researchers detected a 30 metre void above the Grand Gallery. "
                "The void was confirmed with three independent detector systems. "
                "Its intended purpose remains unknown."
            ),
        }

    def test_extracted_text_is_verbatim_and_provenance_is_attached(self):
        claims = extract_claims([self.source], "Great Pyramid void")
        self.assertGreaterEqual(len(claims), 2)
        for claim in claims:
            self.assertIn(claim["text"], self.source["abstract"])
            self.assertEqual(claim["text"], claim["extracted_text"])
            self.assertEqual(claim["source_ids"], ["nature-2017"])
            self.assertEqual(claim["extraction_method"], "abstract_sentence")
            self.assertTrue(claim["provenance"]["abstract_sha256"])

    def test_candidates_never_enter_script_or_gain_final_tier(self):
        claims = extract_claims([self.source], "Great Pyramid void")
        for claim in claims:
            self.assertEqual(claim["status"], "UNKNOWN")
            self.assertFalse(claim["include_in_script"])
            self.assertEqual(claim["review_status"], "UNREVIEWED")
            self.assertEqual(claim["reviewed_by"], "")
            self.assertEqual(claim["reviewed_at"], "")

    def test_empty_abstract_produces_no_claims(self):
        self.assertEqual(extract_claims([{"source_id": "s1", "title": "x"}], "Great Pyramid"), [])

    def test_duplicate_sentence_links_both_sources(self):
        second = dict(self.source, source_id="nature-copy")
        claims = extract_claims([self.source, second], "Great Pyramid void")
        self.assertEqual(claims[0]["source_ids"], ["nature-2017", "nature-copy"])

    def test_unrelated_sentence_is_not_extracted(self):
        source = dict(self.source, abstract="A 30 metre bridge was measured in Rome.")
        self.assertEqual(extract_claims([source], "Great Pyramid void"), [])


if __name__ == "__main__":
    unittest.main()
