import csv
import json
import os
import tempfile
import unittest

from src.verification import verify_ledger
from src.job_state import JobState, run_with_retries
from src.growth import lint_metadata, compare_thumbnail_experiment, import_analytics_csv
from src.documentary import build_documentary
from src.visuals import generate_script_assets


class PhaseExpansionTests(unittest.TestCase):
    def test_verification_flags_bad_date_and_reports_primary_sources(self):
        ledger = {
            "sources": [
                {"source_id": "a", "url": "https://archive.example.org/item",
                 "source_type": "primary", "review_status": "APPROVED", "notes": "Original record"},
                {"source_id": "b", "url": "https://journal.example.com/paper",
                 "source_type": "secondary", "review_status": "APPROVED", "notes": "Peer reviewed"},
            ],
            "claims": [{"claim_id": "c1", "status": "KNOWN", "source_ids": ["a", "b"],
                        "date_start": "1900-02-30"}],
        }
        report = verify_ledger(ledger)
        self.assertFalse(report["passed"])
        self.assertEqual(report["claims"][0]["primary_source_count"], 1)
        self.assertTrue(any("date_start" in e for e in report["claims"][0]["errors"]))
        self.assertIn("truth probability", report["claims"][0]["score_disclaimer"])

    def test_verification_requires_two_domains_for_debated(self):
        ledger = {"sources": [
            {"source_id": "a", "url": "https://same.example.org/a", "review_status": "APPROVED"},
            {"source_id": "b", "url": "https://www.same.example.org/b", "review_status": "APPROVED"}],
            "claims": [{"claim_id": "x", "status": "DEBATED", "source_ids": ["a", "b"]}]}
        report = verify_ledger(ledger)
        self.assertFalse(report["passed"])
        self.assertTrue(any("two domains" in e for e in report["claims"][0]["errors"]))

    def test_job_state_atomic_success_record(self):
        with tempfile.TemporaryDirectory() as td:
            state = JobState(os.path.join(td, "state.json"), run_id="test")
            state.record("research", "success", "ok")
            loaded = JobState(state.path)
            self.assertTrue(loaded.succeeded("research"))

    def test_retry_helper_retries_then_succeeds(self):
        class Result:
            def __init__(self, code):
                self.returncode, self.stderr, self.stdout = code, "fail", ""
        calls = []
        def runner(*args, **kwargs):
            calls.append(1)
            return Result(1 if len(calls) == 1 else 0)
        state = JobState(os.path.join(tempfile.gettempdir(), "deep-scan-test-state.json"))
        result = run_with_retries(["fake"], "test", state=state, runner=runner, sleep=lambda _: None)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(state.succeeded("test"))

    def test_metadata_lint_and_experiment_minimum_exposure(self):
        self.assertFalse(lint_metadata({"recommended_title": "", "description": ""})["passed"])
        result = compare_thumbnail_experiment([
            {"variant": "A", "impressions": 50, "impressions_ctr_pct": 4.0},
            {"variant": "B", "impressions": 60, "impressions_ctr_pct": 5.0}])
        self.assertEqual(result["status"], "insufficient_data")

    def test_analytics_csv_import(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "analytics.csv")
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["Video title", "Views", "Impressions", "Impressions click-through rate (%)"])
                writer.writeheader()
                writer.writerow({"Video title": "Test", "Views": "1,200", "Impressions": "500", "Impressions click-through rate (%)": "4.2%"})
            rows = import_analytics_csv(path)
            self.assertEqual(rows[0]["views"], 1200)
            self.assertEqual(rows[0]["impressions_ctr_pct"], 4.2)


    def test_documentary_builds_only_from_reviewed_claims(self):
        sources = [
            {"source_id": "p", "title": "Archive record", "url": "https://archive.example.org/item",
             "publication": "National Archive", "publication_year": 1901,
             "review_status": "APPROVED", "notes": "Original catalogue record",
             "source_type": "primary"},
            {"source_id": "s", "title": "Research paper", "url": "https://journal.example.com/paper",
             "publication": "History Journal", "publication_year": 2020,
             "review_status": "APPROVED", "notes": "Peer-reviewed analysis",
             "source_type": "secondary"},
        ]
        base = ("A documented historical record describes the event with a precise date, "
                "named location, and surviving material evidence that researchers can examine, rather than relying on later legends or unsupported retellings preserved in the original surviving archive.")
        claims = []
        for i in range(4):
            claims.append({"claim_id": "c{}".format(i + 1), "topic": "Test mystery",
                "text": base, "status": "KNOWN", "source_ids": ["p", "s"],
                "reviewed_by": "human-reviewer", "reviewed_at": "2026-11-09T00:00:00Z",
                "shock_hook": i == 0, "sequence": i + 1})
        package = build_documentary("Test mystery", "short",
                                    {"schema_version": 1, "claims": claims, "sources": sources})
        self.assertEqual(package["style"], "history_mystery")
        self.assertEqual(len(package["scenes"]), 4)
        self.assertIn("AI reconstruction", package["scenes"][0]["visual_type"])
        self.assertTrue(120 <= package["word_count"] <= 180)

    def test_visual_generation_resumes_matching_completed_scenes(self):
        with tempfile.TemporaryDirectory() as td:
            workflow = os.path.join(td, "workflow.json")
            with open(workflow, "w", encoding="utf-8") as fh:
                json.dump({"1": {"inputs": {"text": "{{PROMPT}}"}}}, fh)
            script = {"topic": "Resume test", "format": "short", "scenes": [
                {"scene": 1, "image_prompt": "historical image", "claim_ids": ["c1"]}]}
            calls = []
            import src.visuals as visuals
            original = visuals.generate_scene
            def fake_generate(scene, wf, base, outdir, media_type="image", timeout=600):
                calls.append(1)
                path = os.path.join(outdir, "scene.png")
                with open(path, "wb") as fh:
                    fh.write(b"synthetic image bytes")
                return {"path": path, "type": "image", "scene": scene["scene"]}
            visuals.generate_scene = fake_generate
            try:
                first = generate_script_assets(script, workflow, "http://localhost:8188", td)
                second = generate_script_assets(script, workflow, "http://localhost:8188", td)
            finally:
                visuals.generate_scene = original
            self.assertEqual(len(calls), 1)
            self.assertEqual(first["assets"][0]["path"], second["assets"][0]["path"])


if __name__ == "__main__":
    unittest.main()
