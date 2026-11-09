import unittest
from src.evidence import validate_claim, validate_ledger
from src.documentary import build_documentary


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.source = {"source_id": "s1", "title": "Museum catalogue",
                       "url": "https://museum.example.org/catalogue",
                       "review_status": "APPROVED", "publication": "Museum collection catalogue", "publication_year": 2020, "notes": "Reviewed record"}
        self.sources = {"s1": self.source}

    def test_known_requires_human_review_and_approved_source(self):
        claim = {"claim_id": "c1", "topic": "Test topic", "text": "A documented claim.", "status": "KNOWN",
                 "source_ids": ["s1"], "reviewed_by": "editor",
                 "reviewed_at": "2026-11-09T00:00:00Z"}
        self.assertEqual(validate_claim(claim, self.sources), [])

    def test_unreviewed_claim_is_blocked(self):
        claim = {"claim_id": "c1", "topic": "Test topic", "text": "A claim.", "status": "KNOWN",
                 "source_ids": ["s1"]}
        self.assertTrue(validate_claim(claim, self.sources))

    def test_debated_requires_neutral_disagreement_summary(self):
        claim = {"claim_id": "c1", "topic": "Test topic", "text": "A disputed claim.", "status": "DEBATED",
                 "source_ids": ["s1"], "reviewed_by": "editor",
                 "reviewed_at": "2026-11-09T00:00:00Z"}
        self.assertTrue(any("disagreement" in e for e in validate_claim(claim, self.sources)))

    def test_unapproved_source_blocks_known_claim(self):
        source = dict(self.source, review_status="UNREVIEWED")
        claim = {"claim_id": "c1", "text": "A claim.", "status": "KNOWN",
                 "source_ids": ["s1"], "reviewed_by": "editor",
                 "reviewed_at": "2026-11-09T00:00:00Z"}
        self.assertTrue(validate_claim(claim, {"s1": source}))

    def test_ledger_duplicate_source_ids_block(self):
        source = dict(self.source)
        self.assertTrue(validate_ledger({"sources": [self.source, source], "claims": []}))

    def test_ledger_duplicate_claim_ids_block(self):
        claim = {"claim_id": "c1", "topic": "Test topic", "text": "Claim.", "status": "UNKNOWN",
                 "source_ids": [], "reviewed_by": "editor",
                 "reviewed_at": "2026-11-09T00:00:00Z"}
        self.assertTrue(validate_ledger({"sources": [], "claims": [claim, claim]}))

    def test_documentary_requires_reviewed_shock_hook(self):
        ledger = {"schema_version": 1, "sources": [self.source], "claims": [{
            "claim_id": "c1", "topic": "Test topic", "text": ("A verified historical statement. " * 25), "status": "KNOWN",
            "source_ids": ["s1"], "reviewed_by": "editor",
            "reviewed_at": "2026-11-09T00:00:00Z", "shock_hook": True}]}
        package = build_documentary("Test topic", "short", ledger)
        self.assertEqual(package["claim_ids"], ["c1"])
        self.assertIn("AI reconstruction", package["scenes"][0]["visual_type"])

    def test_long_form_requires_sufficient_reviewed_evidence(self):
        ledger = {"schema_version": 1, "sources": [self.source], "claims": [{
            "claim_id": "c1", "topic": "Test topic", "text": "A short statement.",
            "status": "KNOWN", "source_ids": ["s1"], "reviewed_by": "editor",
            "reviewed_at": "2026-11-09T00:00:00Z", "shock_hook": True}]}
        with self.assertRaisesRegex(ValueError, "1200-1800 words"):
            build_documentary("Test topic", "long", ledger)

    def test_documentary_does_not_invent_hook(self):
        ledger = {"schema_version": 1, "sources": [self.source], "claims": [{
            "claim_id": "c1", "topic": "Test topic", "text": "A statement.", "status": "KNOWN",
            "source_ids": ["s1"], "reviewed_by": "editor",
            "reviewed_at": "2026-11-09T00:00:00Z"}]}
        with self.assertRaises(ValueError):
            build_documentary("Test topic", "short", ledger)


if __name__ == "__main__":
    unittest.main()
