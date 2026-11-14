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


    def test_packet_surfaces_relevance_and_candidate_claims(self):
        research = {"sources": [{
            "source_id": "s1", "title": "Great Pyramid record",
            "url": "https://example.org/record", "provider": "OpenAlex",
            "source_type": "academic", "relevance_score": 82,
            "relevance_reasons": ["title_match"], "review_status": "UNREVIEWED",
            "abstract": "Researchers measured a 30 metre void in the Great Pyramid."
        }], "dropped_sources": [{
            "source": {"source_id": "s2", "title": "Unrelated paper"},
            "relevance_score": 10, "reasons": ["low_term_overlap"]
        }], "relevance_threshold": 40}
        packet = build_packet(research, {"sources": [], "claims": []}, "Great Pyramid")
        row = packet["sources"][0]
        self.assertEqual(row["source_type"], "academic")
        self.assertEqual(row["relevance_score"], 82)
        self.assertEqual(row["relevance_reasons"], ["title_match"])
        self.assertEqual(len(packet["extracted_claims"]), 1)
        self.assertFalse(packet["extracted_claims"][0]["include_in_script"])
        markdown = render_markdown(packet)
        self.assertIn("Relevance score: 82", markdown)
        self.assertIn("Filtered-out discovery candidates", markdown)

if __name__ == "__main__":
    unittest.main()
