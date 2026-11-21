import unittest
from src.review_packet import build_packet, render_markdown


class ReviewPacketTests(unittest.TestCase):
    def test_candidates_remain_unreviewed_and_claim_template_is_blank(self):
        research = {"warning": "Discovery only", "sources": [{
            "source_id": "src_0001", "title": "Catalogue record",
            "url": "https://example.org/record", "provider": "Library",
            "source_priority": "institutional_or_primary",
            "review_status": "UNREVIEWED"
        }]}
        packet = build_packet(research, {"sources": [], "claims": []}, "The lost expedition")
        self.assertEqual(packet["sources"][0]["review_status"], "UNREVIEWED")
        self.assertEqual(packet["sources"][0]["review_decision"], "PENDING")
        self.assertEqual(packet["claim_review_template"]["text"], "")
        self.assertFalse(packet["claim_review_template"]["include_in_script"])
        markdown = render_markdown(packet)
        self.assertIn("not verified evidence", markdown)
        self.assertIn("Never mark a source APPROVED", markdown)

    def test_existing_human_decision_is_reflected_not_overwritten(self):
        research = {"sources": [{"source_id": "src_0001", "title": "Record"}]}
        ledger = {"sources": [{"source_id": "src_0001", "review_status": "APPROVED",
                               "notes": "Checked catalogue item 12"}]}
        packet = build_packet(research, ledger, "Topic")
        self.assertEqual(packet["sources"][0]["review_status"], "APPROVED")
        self.assertEqual(packet["sources"][0]["review_notes"], "Checked catalogue item 12")


if __name__ == "__main__":
    unittest.main()
