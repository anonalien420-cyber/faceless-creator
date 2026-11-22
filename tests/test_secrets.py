"""Tests for Phase 3 item 6: credential leak prevention (src/secrets.py).

Proves, with fake secret values (never real keys):
- redact() removes env-var secret values, ?key= URL parameters,
  Bearer tokens and API-key headers from any text.
- Secrets never reach job state, diagnostics, run logs, QA reports,
  or the narration fallback marker.
- State/diagnostic files the pipeline writes are mode 0600.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.secrets import redact, redact_mapping, write_private_json, write_private_text
from src.job_state import JobState, persist_diagnostic, run_with_retries

FAKE_PEXELS_KEY = "px-FAKESECRETKEY-1234567890abcdef"
FAKE_YT_KEY = "AIzaFAKESECRET-1234567890abcdef"


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class RedactTests(unittest.TestCase):
    def test_env_secret_value_replaced(self):
        with patch.dict(os.environ, {"PEXELS_API_KEY": FAKE_PEXELS_KEY}):
            out = redact(f"failed fetching https://api.pexels.com "
                         f"with key {FAKE_PEXELS_KEY} end")
            self.assertNotIn(FAKE_PEXELS_KEY, out)
            self.assertIn("[REDACTED]", out)

    def test_env_secret_replaced_when_unset_uses_generic_pattern(self):
        # YT key in a URL is caught by the ?key= pattern even when
        # the env var is not set in this process.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YT_API_KEY", None)
            url = ("https://www.googleapis.com/youtube/v3/search"
                   f"?part=snippet&key={FAKE_YT_KEY}")
            out = redact(f"HTTP Error 403: {url}")
            self.assertNotIn(FAKE_YT_KEY, out)
            self.assertIn("key=[REDACTED]", out)

    def test_bearer_token_replaced(self):
        out = redact("Authorization: Bearer abcdefgh1234567890XYZ")
        self.assertNotIn("abcdefgh1234567890XYZ", out)
        self.assertIn("Bearer [REDACTED]", out)

    def test_xi_api_key_header_replaced(self):
        out = redact("{'xi-api-key': 'sk-FAKEELEVENLABSKEY1234567890'}")
        self.assertNotIn("sk-FAKEELEVENLABSKEY1234567890", out)
        self.assertIn("[REDACTED]", out)

    def test_innocent_text_untouched(self):
        text = "narrated with kokoro bm_george, music 0.06, QA 17/19 passed"
        self.assertEqual(redact(text), text)

    def test_short_values_not_redacted(self):
        # A 5-char value must not blank out innocent words.
        with patch.dict(os.environ, {"PEXELS_API_KEY": "short"}):
            self.assertEqual(redact("a short note"), "a short note")

    def test_none_passthrough(self):
        self.assertIsNone(redact(None))

    def test_redact_mapping_recurses(self):
        report = {"run": "2026-11-21", "checks": [
            {"check": "captions_present", "status": "pass",
             "detail": f"fetched with key={FAKE_YT_KEY}"}],
            "log": ["step failed: Bearer abcdefgh1234567890"]}
        with patch.dict(os.environ, {"YT_API_KEY": FAKE_YT_KEY}):
            clean = redact_mapping(report)
        blob = json.dumps(clean)
        self.assertNotIn(FAKE_YT_KEY, blob)
        self.assertNotIn("abcdefgh1234567890", blob)
        self.assertIn("[REDACTED]", blob)


class PrivateWriteTests(unittest.TestCase):
    def test_write_private_json_is_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            write_private_json(path, {"a": 1})
            self.assertEqual(_mode(path), 0o600)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), {"a": 1})

    def test_write_private_text_is_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "diag.log")
            write_private_text(path, "hello")
            self.assertEqual(_mode(path), 0o600)

    def test_private_write_replaces_world_readable_file(self):
        # A pre-existing 0644 file must come back 0600 after rewrite.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{}")
            os.chmod(path, 0o644)
            write_private_json(path, {"b": 2})
            self.assertEqual(_mode(path), 0o600)


class JobStateSecretTests(unittest.TestCase):
    def test_record_redacts_detail_and_file_is_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "job_state.json")
            state = JobState(path)
            with patch.dict(os.environ, {"PEXELS_API_KEY": FAKE_PEXELS_KEY}):
                state.record("fetch", "failed",
                             f"curl error with {FAKE_PEXELS_KEY} in url")
            self.assertEqual(_mode(path), 0o600)
            with open(path, encoding="utf-8") as fh:
                stored = json.load(fh)
            blob = json.dumps(stored)
            self.assertNotIn(FAKE_PEXELS_KEY, blob)
            self.assertIn("[REDACTED]", blob)

    def test_persist_diagnostic_redacts_and_is_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            url = ("https://pixabay.com/api/videos/?key=" + FAKE_YT_KEY
                   + "&q=antikythera")
            diag = persist_diagnostic(
                "stock-fetch", f"HTTP Error 403: {url}\nffmpeg stderr here",
                diagnostics_dir=tmp)
            self.assertEqual(_mode(diag), 0o600)
            with open(diag, encoding="utf-8") as fh:
                content = fh.read()
            self.assertNotIn(FAKE_YT_KEY, content)
            self.assertIn("key=[REDACTED]", content)

    def test_run_with_retries_tail_redacted(self):
        class _Result:
            returncode = 1
            stdout = ""
            stderr = ("curl: (22) https://www.googleapis.com/youtube/v3/"
                      f"search?key={FAKE_YT_KEY} failed")

        def _runner(cmd, capture_output=True, text=True):
            return _Result()

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"YT_API_KEY": FAKE_YT_KEY}):
                with self.assertRaises(RuntimeError) as ctx:
                    run_with_retries(["curl", "https://example.invalid"],
                                     "fetch", attempts=1, runner=_runner,
                                     sleep=lambda s: None)
            self.assertNotIn(FAKE_YT_KEY, str(ctx.exception))
            self.assertIn("[REDACTED]", str(ctx.exception))


class NarrateStateFileTests(unittest.TestCase):
    def test_fallback_marker_is_0600(self):
        from src.narrate import record_narration_fallback
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "narration_fallback.json")
            record_narration_fallback(
                {"fallback": True, "used": "edge-tts"}, path=path)
            self.assertEqual(_mode(path), 0o600)

    def test_run_log_redacts_and_is_0600(self):
        from src.narrate import append_run_log
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with patch.dict(os.environ,
                                {"PEXELS_API_KEY": FAKE_PEXELS_KEY}):
                    append_run_log("fetch",
                                   f"failed with {FAKE_PEXELS_KEY}")
                path = os.path.join(tmp, "data", "run_log.json")
                self.assertEqual(_mode(path), 0o600)
                with open(path, encoding="utf-8") as fh:
                    self.assertNotIn(FAKE_PEXELS_KEY, fh.read())
            finally:
                os.chdir(old)


class RunLogStepTests(unittest.TestCase):
    def test_log_step_redacts_detail(self):
        from src.run import log_step
        log = {"steps": []}
        with patch.dict(os.environ, {"YT_API_KEY": FAKE_YT_KEY}):
            entry = log_step(
                log, "trends", "failed",
                f"youtube api error key={FAKE_YT_KEY}")
        self.assertNotIn(FAKE_YT_KEY, entry["detail"])
        self.assertNotIn(FAKE_YT_KEY, json.dumps(log))
        self.assertIn("[REDACTED]", entry["detail"])


if __name__ == "__main__":
    unittest.main()
