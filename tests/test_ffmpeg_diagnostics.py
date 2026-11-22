"""Regression tests for ffmpeg diagnostics persistence (RC-2/F8).

The Nov 8 / Nov 16 render failures were undiagnosable from CI logs
because ffmpeg stderr was truncated at three layers (video.py kept
the last 12,000 chars, job_state.py -1500/-2000, run.py -4000) and
never persisted whole. These tests prove the full diagnostic text
now lands verbatim in a file artifact and the raised error names
that artifact.

Stdlib + unittest only. The long-diagnostic case runs the REAL ffmpeg
binary (skipped cleanly when ffmpeg is absent): a drawtext filter
with a 15,000-character invalid fontsize value makes ffmpeg fail
with exit code 234 — the same code the Nov 16 daily run reported —
and echo the whole invalid argument list, producing >12,000 chars
of stderr. No network, no rendering of a real video.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.job_state import JobState, persist_diagnostic, run_with_retries
from src.video import _run_ffmpeg

HAS_FFMPEG = bool(shutil.which("ffmpeg"))

# Distinctive marker embedded in the invalid filter argument, so the
# test can prove the artifact holds the diagnostic verbatim (not a
# summary or a truncation): the marker is ~15,000 chars long, which
# alone exceeds the old 12,000-char truncation limit.
LONG_MARKER = "DIAGNOSTIC-MARKER-" + "x" * 14982


def long_filter_error_cmd():
    """argv for a real ffmpeg filter error with >12,000 chars of stderr."""
    return ["ffmpeg", "-y", "-f", "lavfi",
            "-i", "color=c=black:s=64x64:d=0.1",
            "-vf", "drawtext=text='hi':fontsize={}".format(LONG_MARKER),
            "-frames:v", "1", "-f", "null", "-"]


def artifact_path_from_message(message):
    match = re.search(r"full diagnostic saved to (\S+)", message)
    assert match is not None, "error message names no artifact: {!r}".format(message)
    return match.group(1)


class FfmpegDiagnosticsTests(unittest.TestCase):
    def test_long_stderr_persisted_verbatim_and_referenced(self):
        if not HAS_FFMPEG:
            self.skipTest("ffmpeg not available")
        with tempfile.TemporaryDirectory() as tmp:
            env = {"DEEP_SCAN_FFMPEG_DIAGNOSTICS_DIR": tmp}
            with patch.dict(os.environ, env):
                with self.assertRaises(RuntimeError) as ctx:
                    _run_ffmpeg(long_filter_error_cmd(),
                                step="test-long-diagnostic")
            message = str(ctx.exception)
            artifact = artifact_path_from_message(message)
            self.assertTrue(artifact.startswith(tmp),
                            "artifact {!r} is not under the diagnostics dir".format(artifact))
            self.assertTrue(os.path.exists(artifact), "artifact file missing")
            with open(artifact, encoding="utf-8") as fh:
                content = fh.read()
            # (a) The full stderr exists verbatim in the artifact file.
            self.assertGreater(len(content), 12000,
                               "artifact is not longer than the old 12,000-char truncation")
            self.assertIn(LONG_MARKER, content,
                          "artifact does not hold the full diagnostic verbatim")
            # (b) The raised error references the artifact path, and the
            # tail it carries is a suffix of the persisted full text —
            # i.e. nothing was lost, only shortened for readability.
            self.assertIn(artifact, message)
            tail = message.split("full diagnostic saved to {}\n".format(artifact), 1)[1]
            self.assertEqual(tail, content.strip()[-12000:])
            self.assertEqual(len(tail), 12000)

    def test_short_ffmpeg_failure_still_persisted(self):
        if not HAS_FFMPEG:
            self.skipTest("ffmpeg not available")
        with tempfile.TemporaryDirectory() as tmp:
            env = {"DEEP_SCAN_FFMPEG_DIAGNOSTICS_DIR": tmp}
            with patch.dict(os.environ, env):
                with self.assertRaises(RuntimeError) as ctx:
                    _run_ffmpeg(["ffmpeg", "-y", "-i", "/nonexistent-input.mp4",
                                 "-f", "null", "-"], step="test-short-diagnostic")
            artifact = artifact_path_from_message(str(ctx.exception))
            self.assertTrue(os.path.exists(artifact))
            with open(artifact, encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("nonexistent-input.mp4", content)

    def test_artifact_label_defaults_to_output_name(self):
        if not HAS_FFMPEG:
            self.skipTest("ffmpeg not available")
        with tempfile.TemporaryDirectory() as tmp:
            env = {"DEEP_SCAN_FFMPEG_DIAGNOSTICS_DIR": tmp}
            with patch.dict(os.environ, env):
                with self.assertRaises(RuntimeError) as ctx:
                    _run_ffmpeg(["ffmpeg", "-y", "-i", "/nonexistent-input.mp4",
                                 "-f", "null", "my-render.mp4"])
            artifact = artifact_path_from_message(str(ctx.exception))
            self.assertIn("my-render", os.path.basename(artifact))


class PersistDiagnosticTests(unittest.TestCase):
    def test_persist_diagnostic_writes_verbatim_and_returns_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = "line one\n" + "y" * 5000 + "\nline three\n"
            path = persist_diagnostic("unit-step", text, diagnostics_dir=tmp)
            self.assertTrue(path.startswith(tmp))
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), text)


class JobStateDiagnosticsTests(unittest.TestCase):
    def test_run_with_retries_persists_full_diagnostic(self):
        # Fake a subprocess failure whose stderr (5,000 chars) exceeds
        # both the old -1500 detail truncation and the old -2000 raise
        # truncation, so a passing test proves neither truncation
        # discards the full text any more.
        long_stderr = "F" * 4989 + "TAIL-MARKER"
        self.assertEqual(len(long_stderr), 5000)

        def fake_runner(command, capture_output=True, text=True):
            return subprocess.CompletedProcess(command, 1, stdout="",
                                               stderr=long_stderr)

        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "job_state.json")
            env = {"DEEP_SCAN_FFMPEG_DIAGNOSTICS_DIR": tmp}
            with patch.dict(os.environ, env):
                with self.assertRaises(RuntimeError) as ctx:
                    run_with_retries(["ffmpeg", "-y"], "test-step",
                                     state=JobState(state_path),
                                     attempts=1, runner=fake_runner,
                                     sleep=lambda s: None)
            artifact = artifact_path_from_message(str(ctx.exception))
            self.assertTrue(os.path.exists(artifact))
            with open(artifact, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), long_stderr)
            # The state file stays bounded (artifact reference + tail)
            # while the full text lives in the artifact.
            state = JobState(state_path)
            detail = state.data["steps"]["test-step"]["detail"]
            self.assertIn(artifact, detail)
            self.assertLessEqual(len(detail), 2000)
            self.assertNotIn(long_stderr, detail)

    def test_run_with_retries_success_records_no_artifact(self):
        def ok_runner(command, capture_output=True, text=True):
            return subprocess.CompletedProcess(command, 0, stdout="ok",
                                               stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "job_state.json")
            result = run_with_retries(["true"], "ok-step",
                                      state=JobState(state_path),
                                      attempts=1, runner=ok_runner,
                                      sleep=lambda s: None)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(os.listdir(tmp), ["job_state.json"])


if __name__ == "__main__":
    unittest.main()
