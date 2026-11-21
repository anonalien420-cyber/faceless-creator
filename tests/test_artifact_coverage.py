"""Artifact coverage + upload-gate tests for the Deep Scan pipeline.

Stdlib + unittest only. The workflow YAML is parsed by line scan
(no PyYAML dependency) — assertions match on artifact names/paths
as literal lines under the upload-artifact step in daily.yml.
No test performs a real upload: gate behaviour is exercised through
src.upload.main() / src.upload.upload() with env vars patched.
"""
import argparse
import os
import re
import sys
import unittest
from unittest.mock import patch

from src import run as run_module
from src.upload import main as upload_main
from src.upload import upload

TREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_YML = os.path.join(TREE_ROOT, ".github", "workflows", "daily.yml")


def read_daily_yml():
    with open(DAILY_YML, encoding="utf-8") as fh:
        return fh.read()


class DailyArtifactCoverageTests(unittest.TestCase):
    def test_upload_artifact_step_present_with_explicit_retention(self):
        text = read_daily_yml()
        self.assertIn("actions/upload-artifact@v4", text)
        self.assertIn("name: deep-scan-production-", text)
        self.assertIn("retention-days: 14", text)
        self.assertIn("if-no-files-found: warn", text)

    def test_rendered_videos_preserved(self):
        text = read_daily_yml()
        self.assertIn("data/videos_long/**", text)
        self.assertIn("data/videos_short/**", text)

    def test_thumbnails_preserved(self):
        text = read_daily_yml()
        self.assertIn("data/thumbnails/**", text)
        # Thumbnail index map written by src/run.py (thumbnails.json).
        self.assertIn("data/thumbnails.json", text)

    def test_scripts_preserved(self):
        text = read_daily_yml()
        self.assertIn("data/scripts_long.json", text)
        self.assertIn("data/scripts_shorts.json", text)

    def test_run_logs_preserved(self):
        text = read_daily_yml()
        self.assertIn("data/run_log.json", text)
        self.assertIn("data/job_state.json", text)
        self.assertIn("data/series_state.json", text)
        self.assertIn("data/compare.md", text)

    def test_qa_reports_preserved(self):
        text = read_daily_yml()
        self.assertIn("data/qa_report*.json", text)
        # Metadata QA report written by src/run.py; NOT matched by
        # the qa_report*.json glob, so it needs its own line.
        self.assertIn("data/metadata_qa.json", text)

    def test_review_and_evidence_artifacts_preserved(self):
        text = read_daily_yml()
        for path in (
            "data/review_queue.md",
            "data/review_packet.md",
            "data/review_packet.json",
            "data/evidence_ledger.json",
            "data/verification_report.json",
            "data/research_sources.json",
            "data/research_sources_archived.json",
            "data/seo.json",
            "data/generated_visuals/**",
        ):
            with self.subTest(path=path):
                self.assertIn(path, text)

    def test_daily_workflow_cannot_publish(self):
        text = read_daily_yml()
        self.assertNotIn("publish_at_peak", text)
        self.assertNotIn("--public", text)
        self.assertNotIn("--auto-public", text)
        self.assertNotIn("src.upload", text)
        # The only pipeline invocation is render/review-only src.run
        # (no --upload flag passed, so run.py appends --dry-run).
        self.assertIn("python -m src.run", text)
        self.assertNotIn("--upload", text)

    def test_daily_workflow_has_no_publish_flags(self):
        # The remaining publish flags must not appear anywhere in the
        # workflow either (not as inputs, env, or CLI args).
        text = read_daily_yml()
        for flag in ("--publish-at-peak", "--publish-at"):
            with self.subTest(flag=flag):
                self.assertNotIn(flag, text)

    def test_daily_workflow_sets_no_upload_env_vars(self):
        # A scheduled run must not be able to upload even by accident:
        # the workflow sets neither gate variable, so src/upload.py
        # refuses any real upload (see UploadGateTests).
        text = read_daily_yml()
        self.assertNotIn("UPLOAD_ENABLED", text)
        self.assertNotIn("HUMAN_REVIEW_APPROVED", text)

    def test_daily_workflow_invokes_only_render_review(self):
        text = read_daily_yml()
        invoked = sorted(set(re.findall(r"python -m (src\.\w+)", text)))
        self.assertEqual(invoked, ["src.run"])


class UploadGateTests(unittest.TestCase):
    def test_main_refuses_when_both_env_vars_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                upload_main(["--video", "missing.mp4", "--title", "Test"]), 1)

    def test_main_refuses_when_only_upload_enabled_set(self):
        with patch.dict(os.environ,
                        {"UPLOAD_ENABLED": "true"}, clear=True):
            self.assertEqual(
                upload_main(["--video", "missing.mp4", "--title", "Test"]), 1)

    def test_main_refuses_when_only_human_approval_set(self):
        with patch.dict(os.environ,
                        {"HUMAN_REVIEW_APPROVED": "true"}, clear=True):
            self.assertEqual(
                upload_main(["--video", "missing.mp4", "--title", "Test"]), 1)

    def test_main_refuses_every_public_or_scheduled_flag(self):
        env = {"UPLOAD_ENABLED": "true", "HUMAN_REVIEW_APPROVED": "true"}
        cases = [
            ["--public"],
            ["--auto-public"],
            ["--publish-at-peak"],
            ["--publish-at", "2026-11-13T12:00:00Z"],
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                with patch.dict(os.environ, env, clear=True):
                    self.assertEqual(
                        upload_main(["--video", "missing.mp4",
                                     "--title", "Test"] + extra), 1)

    def test_dry_run_still_allowed_without_env_vars(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                upload_main(["--video", "missing.mp4", "--title", "Test",
                             "--dry-run"]), 0)

    def test_upload_function_requires_upload_enabled(self):
        env = {"UPLOAD_ENABLED": "false", "HUMAN_REVIEW_APPROVED": "true"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(PermissionError):
                upload("missing.mp4", "Test", "", "unlisted")

    def test_upload_function_rejects_scheduled_publish(self):
        env = {"UPLOAD_ENABLED": "true", "HUMAN_REVIEW_APPROVED": "true"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                upload("missing.mp4", "Test", "", "unlisted",
                       publish_at="2026-11-13T12:00:00Z")


class ScheduledRunCannotUploadTests(unittest.TestCase):
    """Trace the scheduled-run path end to end: daily.yml -> src/run.py
    -> src/upload.py. daily.yml invokes `python -m src.run` with no
    --upload flag and sets neither UPLOAD_ENABLED nor
    HUMAN_REVIEW_APPROVED, so a scheduled run must reach src/upload.py
    only as a --dry-run (and src/upload.py refuses a real upload
    without both env vars — see UploadGateTests)."""

    def test_upload_outputs_appends_dry_run_without_upload_flag(self):
        captured = []
        args = argparse.Namespace(upload=False)
        outputs = [{"script": {"topic": "Test topic", "text": "hello world"},
                    "video": "data/videos_short/01-test-topic.mp4",
                    "format": "short"}]
        with patch.object(run_module, "run_cmd",
                          side_effect=lambda cmd, step, log: captured.append(cmd)):
            run_module.upload_outputs({"started_at": "2026-11-17T00:00:00Z"},
                                      outputs, "history mysteries", args)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][:4],
                         [sys.executable, "-m", "src.upload", "--video"])
        self.assertIn("--dry-run", captured[0])
        for flag in ("--public", "--auto-public",
                     "--publish-at-peak", "--publish-at"):
            with self.subTest(flag=flag):
                self.assertNotIn(flag, captured[0])


if __name__ == "__main__":
    unittest.main()
