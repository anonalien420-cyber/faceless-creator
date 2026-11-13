"""Recorded-fixture Great Pyramid research-to-documentary integration test.

Only the Nature bibliographic record and short excerpt are real. Other
records are explicitly synthetic test data. This test proves data flow,
provenance and human gating, not historical truth.
"""
import json
import os
import unittest

from src.claim_extraction import extract_claims
from src.documentary import build_documentary
from src.evidence import validate_ledger
from src.relevance import filter_sources, score_source
from src.review_packet import build_packet, render_markdown
from src.verification import verify_ledger


ROOT = os.path.dirname(os.path.dirname(__file__))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "great_pyramid_sources.json")


class GreatPyramidEndToEndTests(unittest.TestCase):
    def test_discovery_to_reviewed_documentary_gate(self):
        with open(FIXTURE, encoding="utf-8") as handle:
            fixture = json.load(handle)
        sources = fixture["sources"]
        query = fixture["query"]

        kept, dropped = filter_sources(sources, query, threshold=40)
        ranked = sorted(kept, key=lambda row: score_source(row, query)["score"], reverse=True)
        self.assertEqual(ranked[0]["source_id"], "nature_2017")
        self.assertTrue(any(row["source"]["source_id"] == "irrelevant_finance"
                            for row in dropped))

        candidates = extract_claims(ranked, fixture["topic"])
        self.assertGreaterEqual(len(candidates), 3)
        for candidate in candidates:
            self.assertEqual(candidate["status"], "UNKNOWN")
            self.assertFalse(candidate["include_in_script"])
            self.assertEqual(candidate["review_status"], "UNREVIEWED")

        research = {
            "sources": ranked,
            "dropped_sources": dropped,
            "warning": "Discovery candidates only; human review required."
        }
        packet = build_packet(research, {"sources": [], "claims": []}, fixture["topic"])
        self.assertEqual(len(packet["extracted_claims"]), len(candidates))
        self.assertIn("UNREVIEWED", render_markdown(packet))

        # Before a human approves sources and writes reviewed claims, the
        # evidence ledger must remain blocked.
        blocked = {
            "schema_version": 2,
            "sources": [dict(row, notes="") for row in ranked],
            "claims": [{
                "claim_id": candidate["claim_id"],
                "topic": fixture["topic"],
                "text": candidate["text"],
                "status": "UNKNOWN",
                "source_ids": candidate["source_ids"],
                "reviewed_by": "",
                "reviewed_at": "",
            } for candidate in candidates],
        }
        self.assertTrue(validate_ledger(blocked))

        # A separate fixture simulates explicit human review. No extraction
        # result itself is allowed to flip approval or include_in_script.
        approved_sources = []
        for source in ranked:
            approved_sources.append(dict(
                source,
                review_status="APPROVED",
                notes="Synthetic reviewer fixture: source inspected for pipeline test."
            ))
        reviewed_claims = []
        for index, candidate in enumerate(candidates):
            source_ids = candidate["source_ids"]
            reviewed_claims.append({
                "claim_id": "reviewed_{}".format(index + 1),
                "topic": fixture["topic"],
                "text": candidate["text"],
                "status": "KNOWN" if candidate["suggested_status"] == "KNOWN" else "UNKNOWN",
                "source_ids": source_ids,
                "reviewed_by": "fixture-human-reviewer",
                "reviewed_at": "2026-11-13T00:00:00Z",
                "sequence": index + 1,
                "shock_hook": index == 0,
                "include_in_script": True,
            })
        # Only the first extracted candidate is guaranteed to be a KNOWN hook.
        reviewed_claims[0]["status"] = "KNOWN"
        ledger = {
            "schema_version": 2,
            "sources": approved_sources,
            "claims": reviewed_claims,
        }
        self.assertEqual(validate_ledger(ledger), [])
        verification = verify_ledger(ledger)
        self.assertTrue(verification["passed"])
        package = build_documentary(fixture["topic"], "short", ledger)
        self.assertTrue(120 <= package["word_count"] <= 180)
        self.assertEqual(set(package["claim_ids"]),
                         {claim["claim_id"] for claim in reviewed_claims})
        self.assertTrue(package["shock_hook"]["text"])


if __name__ == "__main__":
    unittest.main()
