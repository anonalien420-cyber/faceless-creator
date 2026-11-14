import unittest
from unittest.mock import patch

from src.run import evaluate_historical_production_gate


class HistoricalProductionGateTests(unittest.TestCase):
    def setUp(self):
        self.niche = "history mysteries investigated with modern tech"
        self.long_candidates = [{"topic": "Lost city investigation"}]
        self.short_candidates = [
            {"topic": "Ancient artifact mystery"},
            {"topic": "Unexplained historical event"},
        ]
        self.empty_ledger = {"schema_version": 2, "sources": [], "claims": []}
        self.reviewed_ledger = {
            "schema_version": 2,
            "sources": [],
            "claims": [{
                "claim_id": "claim-1",
                "topic": "Lost city investigation",
                "text": "A reviewed but unresolved historical question.",
                "status": "UNKNOWN",
                "source_ids": [],
                "reviewed_by": "human-reviewer",
                "reviewed_at": "2026-11-13T00:00:00Z",
            }],
        }

    def test_empty_ledger_blocks_without_calling_script_builder(self):
        with patch("src.documentary.build_documentary") as builder:
            result = evaluate_historical_production_gate(
                self.niche, self.long_candidates, self.short_candidates,
                self.empty_ledger)

        self.assertEqual(result["status"], "blocked_review_required")
        self.assertEqual(result["reviewed_claim_count"], 0)
        self.assertEqual(len(result["blockers"]), 1)
        self.assertEqual(builder.call_count, 0)

    def test_all_planned_formats_and_topics_are_preflighted(self):
        with patch("src.documentary.build_documentary", return_value={"ok": True}) as builder:
            result = evaluate_historical_production_gate(
                self.niche, self.long_candidates, self.short_candidates,
                self.reviewed_ledger)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["reviewed_claim_count"], 1)
        self.assertEqual(builder.call_count, 3)
        self.assertEqual(
            [(item["format"], item["topic"]) for item in result["topics"]],
            [
                ("long", "Lost city investigation"),
                ("short", "Ancient artifact mystery"),
                ("short", "Unexplained historical event"),
            ],
        )

    def test_one_topic_failure_blocks_the_entire_slate(self):
        def build(topic, fmt, ledger):
            if topic == "Unexplained historical event":
                raise ValueError("No reviewed claims match this topic.")
            return {"ok": True}

        with patch("src.documentary.build_documentary", side_effect=build):
            result = evaluate_historical_production_gate(
                self.niche, self.long_candidates, self.short_candidates,
                self.reviewed_ledger)

        self.assertEqual(result["status"], "blocked_review_required")
        self.assertEqual(len(result["blockers"]), 1)
        self.assertEqual(result["topics"][-1]["status"], "blocked_review_required")

    def test_invalid_ledger_is_blocked_not_auto_approved(self):
        invalid = {
            "schema_version": 2,
            "sources": [],
            "claims": [{
                "claim_id": "unreviewed",
                "topic": "Lost city investigation",
                "text": "An unreviewed claim.",
                "status": "KNOWN",
                "source_ids": [],
            }],
        }
        result = evaluate_historical_production_gate(
            self.niche, self.long_candidates, self.short_candidates, invalid)

        self.assertEqual(result["status"], "blocked_review_required")
        self.assertIn("Evidence ledger is not publishable", result["blockers"][0])

    def test_non_historical_niche_does_not_require_evidence_gate(self):
        result = evaluate_historical_production_gate(
            "productivity tips", self.long_candidates, self.short_candidates,
            self.empty_ledger)

        self.assertFalse(result["required"])
        self.assertEqual(result["status"], "ready")


if __name__ == "__main__":
    unittest.main()
