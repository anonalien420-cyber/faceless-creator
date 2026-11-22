"""Tests for the real Antikythera evidence ledger.

These tests load the actual ``data/evidence_ledger.json`` (transcribed
human-reviewed claims from the published Antikythera long-form) and
assert the production gates pass on it. They are not fixture tests:
if the ledger file is edited, these tests check the edited ledger.
No network is involved.
"""
import json
import os
import unittest
from urllib.parse import urlparse

from src.documentary import build_documentary
from src.evidence import load_ledger, validate_ledger, reviewed_claims
from src.verification import verify_ledger

TOPIC = "The 2,000-Year-Old Object That Shouldn't Exist"
LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "data",
                           "evidence_ledger.json")


def _valid_url(url):
    parsed = urlparse(url or "")
    return parsed.scheme in ("http", "https") and "." in (parsed.netloc or "")


class RealLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = load_ledger(LEDGER_PATH)
        cls.sources = {s["source_id"]: s
                       for s in cls.ledger.get("sources", [])}

    def test_ledger_file_exists_and_loads(self):
        self.assertTrue(os.path.isfile(LEDGER_PATH))
        self.assertEqual(self.ledger.get("schema_version"), 1)

    def test_validation_gate_passes(self):
        self.assertEqual(validate_ledger(self.ledger), [])

    def test_claim_count_and_tier_breakdown(self):
        claims = self.ledger["claims"]
        self.assertEqual(len(claims), 12)
        tiers = {status: sum(1 for c in claims if c["status"] == status)
                 for status in ("KNOWN", "DEBATED", "UNKNOWN")}
        self.assertEqual(tiers, {"KNOWN": 10, "DEBATED": 1, "UNKNOWN": 1})

    def test_every_claim_has_human_reviewer_and_review_window(self):
        for claim in self.ledger["claims"]:
            self.assertEqual(claim["reviewed_by"], "Kristian",
                             claim["claim_id"])
            reviewed_at = claim["reviewed_at"]
            self.assertTrue("2026-11-03" <= reviewed_at <= "2026-11-06",
                            claim["claim_id"] + ": " + reviewed_at)
            self.assertEqual(claim["topic"], TOPIC)
            self.assertTrue(claim["text"].strip())

    def test_every_source_is_approved_with_real_url_and_notes(self):
        self.assertEqual(len(self.ledger["sources"]), 6)
        for source in self.ledger["sources"]:
            self.assertEqual(source["review_status"], "APPROVED",
                             source["source_id"])
            self.assertTrue(source["title"].strip())
            self.assertTrue(_valid_url(source["url"]), source["source_id"])
            self.assertTrue(source.get("publication")
                            or source.get("publication_year")
                            or source.get("provider"))
            self.assertTrue(source["notes"].strip())
            lowered = (source["title"] + " " + source["notes"]).lower()
            for placeholder in ("placeholder", "do not publish",
                                "to cite before publishing"):
                self.assertNotIn(placeholder, lowered)

    def test_source_urls_are_distinct(self):
        urls = [s["url"] for s in self.ledger["sources"]]
        self.assertEqual(len(urls), len(set(urls)))

    def test_known_and_debated_claims_link_approved_sources(self):
        for claim in self.ledger["claims"]:
            if claim["status"] in ("KNOWN", "DEBATED"):
                self.assertTrue(claim["source_ids"], claim["claim_id"])
                for source_id in claim["source_ids"]:
                    self.assertIn(source_id, self.sources)
                    self.assertEqual(
                        self.sources[source_id]["review_status"], "APPROVED")

    def test_debated_claim_has_two_sources_and_both_positions(self):
        debated = [c for c in self.ledger["claims"]
                   if c["status"] == "DEBATED"]
        self.assertEqual(len(debated), 1)
        claim = debated[0]
        self.assertGreaterEqual(len(set(claim["source_ids"])), 2)
        self.assertTrue(claim["debate_summary"].strip())
        self.assertTrue(claim["position_a"].strip())
        self.assertTrue(claim["position_b"].strip())

    def test_unknown_claim_names_no_builder(self):
        unknown = [c for c in self.ledger["claims"]
                   if c["status"] == "UNKNOWN"]
        self.assertEqual(len(unknown), 1)
        self.assertIn("builder", unknown[0]["text"])

    def test_hook_claim_is_known_and_flagged(self):
        hooks = [c for c in self.ledger["claims"] if c.get("shock_hook")]
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0]["status"], "KNOWN")

    def test_provenance_states_transcription_not_self_approval(self):
        provenance = self.ledger.get("provenance", "")
        self.assertIn("transcribed into this ledger on 2026-11-15", provenance)
        self.assertIn("NOT self-approval", provenance)
        self.assertIn("k_wGkEfT5QI", json.dumps(self.ledger))

    def test_reviewed_claims_returns_all_twelve(self):
        self.assertEqual(len(reviewed_claims(self.ledger)), 12)

    def test_verification_passes_with_no_review_flag(self):
        report = verify_ledger(self.ledger)
        self.assertTrue(report["passed"])
        self.assertFalse(report["needs_review"])
        for result in report["claims"]:
            self.assertEqual(result["errors"], [], result["claim_id"])

    def test_short_documentary_builds_from_reviewed_claims(self):
        package = build_documentary(TOPIC, "short", self.ledger)
        self.assertTrue(120 <= package["word_count"] <= 180)
        self.assertEqual(package["claim_ids"], [
            "antikythera_01", "antikythera_02", "antikythera_03",
            "antikythera_04", "antikythera_05", "antikythera_09",
            "antikythera_10"])
        self.assertEqual(
            package["hook"],
            "A geared bronze machine that predicted eclipses existed in "
            "the ancient world about two thousand years ago.")


if __name__ == "__main__":
    unittest.main()
