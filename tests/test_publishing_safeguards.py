import os
import unittest
from unittest.mock import patch
from src.upload import main, upload


class PublishingSafeguardTests(unittest.TestCase):
    @patch.dict(os.environ, {"UPLOAD_ENABLED": "true", "HUMAN_REVIEW_APPROVED": "false"})
    def test_upload_without_human_approval_is_refused(self):
        self.assertEqual(main(["--video", "missing.mp4", "--title", "Test"]), 1)

    @patch.dict(os.environ, {"UPLOAD_ENABLED": "true", "HUMAN_REVIEW_APPROVED": "true"})
    def test_public_upload_is_never_allowed(self):
        self.assertEqual(main(["--video", "missing.mp4", "--title", "Test", "--public"]), 1)

    @patch.dict(os.environ, {"UPLOAD_ENABLED": "false"})
    def test_dry_run_does_not_upload(self):
        self.assertEqual(main(["--video", "missing.mp4", "--title", "Test", "--dry-run"]), 0)

    @patch.dict(os.environ, {"UPLOAD_ENABLED": "true", "HUMAN_REVIEW_APPROVED": "true"})
    def test_upload_function_rejects_public_privacy(self):
        with self.assertRaises(ValueError):
            upload("missing.mp4", "Test", "", "public")

    @patch.dict(os.environ, {"UPLOAD_ENABLED": "true", "HUMAN_REVIEW_APPROVED": "false"})
    def test_upload_function_requires_human_approval(self):
        with self.assertRaises(PermissionError):
            upload("missing.mp4", "Test", "", "unlisted")

    @patch.dict(os.environ, {"UPLOAD_ENABLED": "false", "HUMAN_REVIEW_APPROVED": "true"})
    def test_upload_function_requires_upload_enabled(self):
        with self.assertRaises(PermissionError):
            upload("missing.mp4", "Test", "", "unlisted")

    @patch.dict(os.environ, {"UPLOAD_ENABLED": "true", "HUMAN_REVIEW_APPROVED": "true"})
    def test_upload_function_rejects_scheduled_publish(self):
        with self.assertRaises(ValueError):
            upload("missing.mp4", "Test", "", "unlisted",
                   publish_at="2026-11-13T12:00:00Z")

    @patch.dict(os.environ, {"UPLOAD_ENABLED": "true", "HUMAN_REVIEW_APPROVED": "true"})
    def test_scheduled_publish_flags_are_refused(self):
        for extra in (["--auto-public"], ["--publish-at-peak"],
                      ["--publish-at", "2026-11-13T12:00:00Z"]):
            with self.subTest(extra=extra):
                self.assertEqual(
                    main(["--video", "missing.mp4", "--title", "Test"] + extra), 1)

    @patch.dict(os.environ, {"HUMAN_REVIEW_APPROVED": "true"})
    def test_main_refuses_without_upload_enabled(self):
        self.assertEqual(main(["--video", "missing.mp4", "--title", "Test"]), 1)

    def test_run_py_has_no_public_publish_flags(self):
        # Defense in depth: src/run.py must not define or forward any
        # public/scheduled-publish flag. The only remaining mentions
        # are the comment explaining their deliberate absence.
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "src", "run.py"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn('add_argument("--public"', text)
        self.assertNotIn('add_argument("--auto-public"', text)
        self.assertNotIn('add_argument("--publish-at-peak"', text)
        self.assertNotIn("args.public", text)
        self.assertNotIn("args.auto_public", text)
        self.assertNotIn("args.publish_at_peak", text)
        self.assertNotIn('"--public"', text)
        self.assertNotIn('"--auto-public"', text)
        self.assertNotIn('"--publish-at-peak"', text)

    def test_weekly_review_never_auto_commits_config(self):
        # Audit Blocker 4: the weekly review workflow must not commit
        # or push config.yaml unattended. Review outputs only.
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, ".github", "workflows", "weekly-review.yml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("git add"):
                self.assertNotIn("config.yaml", stripped)


if __name__ == "__main__":
    unittest.main()
