import os
import unittest
from unittest.mock import patch
from src.upload import main


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


if __name__ == "__main__":
    unittest.main()
