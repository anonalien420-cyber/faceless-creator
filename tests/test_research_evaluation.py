"""Tests for the human-labelled research precision evaluator."""
import unittest

from src.research_evaluation import evaluate_precision_at_k, compare_precision_at_k


class ResearchEvaluationTests(unittest.TestCase):
    def test_mean_precision_at_k_uses_only_human_labels(self):
        dataset = {"topics": [
            {"topic": "Great Pyramid", "results": [
                {"source_id": "a{}".format(i), "relevant": i < 8} for i in range(10)
            ]},
            {"topic": "Antikythera mechanism", "results": [
                {"source_id": "b{}".format(i), "relevant": i < 6} for i in range(10)
            ]},
        ]}
        report = evaluate_precision_at_k(dataset, k=10)
        self.assertEqual(report["topic_count"], 2)
        self.assertEqual(report["mean_precision_at_k"], 0.7)
        self.assertIn("not source authenticity", report["disclaimer"])

    def test_missing_human_label_blocks_metric(self):
        dataset = {"topics": [{"topic": "topic", "results": [
            {"source_id": "s{}".format(i), "relevant": True} for i in range(9)
        ] + [{"source_id": "s9"}]}]}
        with self.assertRaisesRegex(ValueError, "human boolean relevance label"):
            evaluate_precision_at_k(dataset, k=10)

    def test_incomplete_top_k_blocks_metric(self):
        with self.assertRaisesRegex(ValueError, "at least 10 labelled results"):
            evaluate_precision_at_k({"topics": [{
                "topic": "topic", "results": [{"source_id": "s1", "relevant": True}]
            }]}, k=10)

    def test_duplicate_source_ids_block_metric(self):
        dataset = {"topics": [{"topic": "topic", "results": [
            {"source_id": "same", "relevant": True},
            {"source_id": "same", "relevant": False},
        ]}]}
        with self.assertRaisesRegex(ValueError, "duplicate source_id"):
            evaluate_precision_at_k(dataset, k=2)


    def test_comparison_reports_phase2_delta_without_claiming_truth(self):
        dataset = {
            "baseline": {"topics": [{"topic": "topic", "results": [
                {"source_id": "b{}".format(i), "relevant": i < 4} for i in range(10)
            ]}]},
            "phase2": {"topics": [{"topic": "topic", "results": [
                {"source_id": "p{}".format(i), "relevant": i < 7} for i in range(10)
            ]}]},
        }
        report = compare_precision_at_k(dataset, k=10)
        self.assertAlmostEqual(report["absolute_delta"], 0.3)
        self.assertIn("not claim truth", report["disclaimer"])

if __name__ == "__main__":
    unittest.main()
