import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from src.upload import main, plan, upload

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _clean_env():
    """Env without either upload gate, so CLI tests are hermetic."""
    env = dict(os.environ)
    env.pop("UPLOAD_ENABLED", None)
    env.pop("HUMAN_REVIEW_APPROVED", None)
    return env


class _FakeCredentials:
    """Stand-in for google.oauth2.credentials.Credentials."""
    valid = True
    expired = False
    refresh_token = None

    @classmethod
    def from_authorized_user_file(cls, path, scopes):
        return cls()

    def to_json(self):
        return "{}"


class _FakeMediaFileUpload:
    def __init__(self, filename, chunksize=-1, resumable=True):
        self.filename = filename
        self.chunksize = chunksize
        self.resumable = resumable


class _FakeInsertRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def execute(self):
        return {"id": "VIDEOID123"}

    def next_chunk(self):
        # Resumable path (src/upload.py drives next_chunk, not
        # execute): one chunk completes the upload.
        return None, {"id": "VIDEOID123"}


class _FakeVideos:
    def __init__(self, calls):
        self.calls = calls

    def insert(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeInsertRequest(**kwargs)


class _FakeYouTube:
    def __init__(self, calls):
        self.calls = calls

    def videos(self):
        return _FakeVideos(self.calls)


def _fake_google_modules(calls):
    """sys.modules entries stubbing the Google client libraries so
    upload() can be exercised without network or real credentials."""
    flow_mod = types.ModuleType("google_auth_oauthlib.flow")
    flow_mod.InstalledAppFlow = object  # unused on the token.json path
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = object
    credentials_mod = types.ModuleType("google.oauth2.credentials")
    credentials_mod.Credentials = _FakeCredentials
    discovery_mod = types.ModuleType("googleapiclient.discovery")
    discovery_mod.build = lambda *args, **kwargs: _FakeYouTube(calls)
    http_mod = types.ModuleType("googleapiclient.http")
    http_mod.MediaFileUpload = _FakeMediaFileUpload
    return {
        "google": types.ModuleType("google"),
        "google.auth": types.ModuleType("google.auth"),
        "google.auth.transport": types.ModuleType("google.auth.transport"),
        "google.auth.transport.requests": requests_mod,
        "google.oauth2": types.ModuleType("google.oauth2"),
        "google.oauth2.credentials": credentials_mod,
        "google_auth_oauthlib": types.ModuleType("google_auth_oauthlib"),
        "google_auth_oauthlib.flow": flow_mod,
        "googleapiclient": types.ModuleType("googleapiclient"),
        "googleapiclient.discovery": discovery_mod,
        "googleapiclient.http": http_mod,
    }


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

    def test_plan_rejects_public_privacy(self):
        # plan() must enforce the same policy as upload(): no caller
        # may build a public plan through this helper.
        with self.assertRaises(ValueError):
            plan("video.mp4", "Test", "", "public")

    def test_plan_rejects_scheduled_publish(self):
        with self.assertRaises(ValueError):
            plan("video.mp4", "Test", "", "unlisted",
                 publish_at="2026-11-13T12:00:00Z")

    def test_plan_allows_unlisted_unscheduled(self):
        planned = plan("video.mp4", "Test", "Desc", "unlisted")
        self.assertEqual(planned["privacyStatus"], "unlisted")
        self.assertNotIn("publishAt", planned)
        self.assertEqual(planned["categoryId"], "27")

    @patch.dict(os.environ, {"UPLOAD_ENABLED": "true", "HUMAN_REVIEW_APPROVED": "true"})
    def test_upload_with_both_gates_is_unlisted_without_publish_at(self):
        # Positive-path proof at uploader level: with BOTH gates set,
        # the YouTube insert body must be unlisted with no publishAt.
        # Google client libraries are stubbed (no network, no real
        # credentials); a fake token.json keeps upload() off the OAuth
        # flow, and the test runs in a temp cwd so nothing is written
        # into the repo.
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "token.json"), "w") as fh:
                fh.write("{}")
            video = os.path.join(directory, "video.mp4")
            with open(video, "wb") as fh:
                fh.write(b"fake mp4")
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                with patch.dict(sys.modules, _fake_google_modules(calls)):
                    video_id = upload(video, "Test Title", "Test desc",
                                      "unlisted")
            finally:
                os.chdir(old_cwd)
        self.assertEqual(video_id, "VIDEOID123")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["part"], "snippet,status")
        body = calls[0]["body"]
        self.assertEqual(body["status"], {"privacyStatus": "unlisted"})
        self.assertNotIn("publishAt", body["status"])
        self.assertEqual(body["snippet"]["title"], "Test Title")
        self.assertEqual(body["snippet"]["description"], "Test desc")
        self.assertEqual(body["snippet"]["categoryId"], "27")
        self.assertEqual(calls[0]["media_body"].filename, video)

    def test_cli_public_flags_are_refused_by_upload(self):
        # CLI level: `python -m src.upload --public` (and friends)
        # must exit 1, never reach the gates, never upload.
        for extra in (["--public"], ["--auto-public"],
                      ["--publish-at-peak"],
                      ["--publish-at", "2026-11-13T12:00:00Z"]):
            with self.subTest(extra=extra):
                result = subprocess.run(
                    [sys.executable, "-m", "src.upload",
                     "--video", "missing.mp4", "--title", "Test"] + extra,
                    cwd=REPO_ROOT, env=_clean_env(),
                    capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("disabled", result.stderr)

    def test_cli_dry_run_does_not_override_public_refusal(self):
        # The flag check precedes the dry-run shortcut: --dry-run
        # must not launder a --public request into a success.
        result = subprocess.run(
            [sys.executable, "-m", "src.upload",
             "--video", "missing.mp4", "--title", "Test",
             "--dry-run", "--public"],
            cwd=REPO_ROOT, env=_clean_env(),
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_cli_public_flags_are_rejected_by_run(self):
        # src/run.py defines no public/scheduled-publish flag at all:
        # argparse must refuse them (exit 2) before any work happens.
        for extra in (["--public"], ["--auto-public"],
                      ["--publish-at-peak"],
                      ["--publish-at", "2026-11-13T12:00:00Z"]):
            with self.subTest(extra=extra):
                result = subprocess.run(
                    [sys.executable, "-m", "src.run"] + extra,
                    cwd=REPO_ROOT, env=_clean_env(),
                    capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("unrecognized arguments", result.stderr)

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
