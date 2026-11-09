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


if __name__ == "__main__":
    unittest.main()
