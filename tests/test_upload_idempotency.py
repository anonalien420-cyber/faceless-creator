"""Upload retry idempotency (Phase 3, item 1).

A retried upload must never create a duplicate video: the same
(video bytes, title, description) returns the already-uploaded video
id without calling the API again, a transient failure resumes the
same resumable upload, and the upload-state file is written
atomically with owner-only permissions. A corrupt state file must
not block a legitimate upload.

Google client libraries are stubbed (no network, no real
credentials), following tests/test_publishing_safeguards.py.
"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.upload import (
    DEFAULT_UPLOAD_STATE_PATH,
    find_completed_upload,
    load_upload_state,
    record_completed_upload,
    resumable_upload,
    upload,
    upload_fingerprint,
)


class _FakeCredentials:
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


class _FlakyInsertRequest:
    """Fails next_chunk() `fail_times` times (transient), then succeeds."""

    def __init__(self, calls, fail_times=1, fail_exc=None):
        self.calls = calls
        self.fail_times = fail_times
        self.fail_exc = fail_exc or ConnectionError("simulated network drop")
        self.attempts = 0

    def next_chunk(self):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise self.fail_exc
        return None, {"id": "VIDEOID123"}

    def execute(self):
        return {"id": "VIDEOID123"}


class _FakeVideos:
    def __init__(self, calls, request_factory):
        self.calls = calls
        self.request_factory = request_factory

    def insert(self, **kwargs):
        self.calls.append(kwargs)
        return self.request_factory(self.calls)


class _FakeYouTube:
    def __init__(self, calls, request_factory):
        self.calls = calls
        self.request_factory = request_factory

    def videos(self):
        return _FakeVideos(self.calls, self.request_factory)


def _fake_google_modules(calls, request_factory=None):
    factory = request_factory or (lambda calls: _FlakyInsertRequest(calls, fail_times=0))
    flow_mod = types.ModuleType("google_auth_oauthlib.flow")
    flow_mod.InstalledAppFlow = object
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = object
    credentials_mod = types.ModuleType("google.oauth2.credentials")
    credentials_mod.Credentials = _FakeCredentials
    discovery_mod = types.ModuleType("googleapiclient.discovery")
    discovery_mod.build = lambda *args, **kwargs: _FakeYouTube(calls, factory)
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


class _UploadHarness:
    """Context manager: temp cwd + stubbed Google libs + fake token."""

    def __init__(self, request_factory=None):
        self.request_factory = request_factory
        self.calls = []
        self.tmp = None
        self.old_cwd = None
        self.video = None
        self.state_path = None

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        with open("token.json", "w") as fh:
            fh.write("{}")
        self.video = os.path.join(self.tmp.name, "video.mp4")
        with open(self.video, "wb") as fh:
            fh.write(b"fake mp4 bytes for idempotency test")
        self.state_path = os.path.join(self.tmp.name, "upload_state.json")
        self._patcher = patch.dict(
            sys.modules, _fake_google_modules(self.calls, self.request_factory))
        self._patcher.__enter__()
        return self

    def __exit__(self, *exc):
        self._patcher.__exit__(*exc)
        os.chdir(self.old_cwd)
        self.tmp.cleanup()
        return False

    def run_upload(self, title="Test Title", description="Test desc"):
        return upload(self.video, title, description, "unlisted",
                      state_path=self.state_path)


@patch.dict(os.environ, {"UPLOAD_ENABLED": "true", "HUMAN_REVIEW_APPROVED": "true"})
class UploadIdempotencyTests(unittest.TestCase):
    def test_retry_returns_same_video_id_without_second_insert(self):
        with _UploadHarness() as harness:
            first = harness.run_upload()
            second = harness.run_upload()
        self.assertEqual(first, "VIDEOID123")
        self.assertEqual(second, "VIDEOID123")
        # Only ONE insert call: the retry never touched the API.
        self.assertEqual(len(harness.calls), 1)

    def test_different_title_is_a_different_upload(self):
        with _UploadHarness() as harness:
            harness.run_upload(title="Title A")
            harness.run_upload(title="Title B")
        self.assertEqual(len(harness.calls), 2)

    def test_transient_failure_resumes_and_succeeds(self):
        factory = lambda calls: _FlakyInsertRequest(calls, fail_times=2)
        with _UploadHarness(request_factory=factory) as harness:
            video_id = harness.run_upload()
        self.assertEqual(video_id, "VIDEOID123")
        # One insert call; the same request object was retried.
        self.assertEqual(len(harness.calls), 1)

    def test_non_retryable_error_fails_fast(self):
        class _BadRequest(Exception):
            def __init__(self):
                super().__init__("invalidTitle")
                self.resp = types.SimpleNamespace(status=400)

        factory = lambda calls: _FlakyInsertRequest(
            calls, fail_times=5, fail_exc=_BadRequest())
        with _UploadHarness(request_factory=factory) as harness:
            with self.assertRaises(RuntimeError) as ctx:
                harness.run_upload()
        self.assertIn("not retryable", str(ctx.exception))
        self.assertEqual(len(harness.calls), 1)

    def test_state_file_is_owner_only_and_records_video_id(self):
        with _UploadHarness() as harness:
            harness.run_upload()
            mode = os.stat(harness.state_path).st_mode & 0o777
            self.assertEqual(mode, 0o600)
            with open(harness.state_path, encoding="utf-8") as fh:
                state = json.load(fh)
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(len(state["uploads"]), 1)
        entry = next(iter(state["uploads"].values()))
        self.assertEqual(entry["video_id"], "VIDEOID123")

    def test_corrupt_state_file_does_not_block_upload(self):
        with _UploadHarness() as harness:
            with open(harness.state_path, "w") as fh:
                fh.write("{not json")
            video_id = harness.run_upload()
        self.assertEqual(video_id, "VIDEOID123")
        self.assertEqual(len(harness.calls), 1)

    def test_fingerprint_changes_with_file_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.mp4")
            b = os.path.join(tmp, "b.mp4")
            with open(a, "wb") as fh:
                fh.write(b"bytes one")
            with open(b, "wb") as fh:
                fh.write(b"bytes two")
            self.assertNotEqual(
                upload_fingerprint(a, "T", "D"),
                upload_fingerprint(b, "T", "D"))
            self.assertEqual(
                upload_fingerprint(a, "T", "D"),
                upload_fingerprint(a, "T", "D"))


class ResumableUploadTests(unittest.TestCase):
    def test_resumable_upload_returns_response_when_done(self):
        request = _FlakyInsertRequest([], fail_times=0)
        response = resumable_upload(request, sleep=lambda s: None)
        self.assertEqual(response, {"id": "VIDEOID123"})
        self.assertEqual(request.attempts, 1)

    def test_resumable_upload_retries_transient_errors(self):
        request = _FlakyInsertRequest([], fail_times=2)
        response = resumable_upload(request, sleep=lambda s: None)
        self.assertEqual(response, {"id": "VIDEOID123"})
        self.assertEqual(request.attempts, 3)

    def test_resumable_upload_gives_up_after_max_attempts(self):
        request = _FlakyInsertRequest([], fail_times=10)
        with self.assertRaises(RuntimeError) as ctx:
            resumable_upload(request, max_attempts=3, sleep=lambda s: None)
        self.assertIn("3 attempt", str(ctx.exception))
        self.assertEqual(request.attempts, 3)


class UploadStateHelpersTests(unittest.TestCase):
    def test_load_missing_state_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = load_upload_state(os.path.join(tmp, "nope.json"))
        self.assertEqual(state, {"schema_version": 1, "uploads": {}})

    def test_find_completed_upload_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            state = load_upload_state(path)
            self.assertIsNone(find_completed_upload(state, "abc"))
            record_completed_upload(state, "abc", "VID1", "v.mp4",
                                    "Title", path)
            state2 = load_upload_state(path)
            self.assertEqual(find_completed_upload(state2, "abc"), "VID1")
            self.assertIsNone(find_completed_upload(state2, "other"))

    def test_default_state_path_is_under_data(self):
        self.assertEqual(DEFAULT_UPLOAD_STATE_PATH, "data/upload_state.json")


if __name__ == "__main__":
    unittest.main()
