"""Regression tests for F1 (silent-skip): a render step that produces no
MP4 must fail the run loudly, and the run summary must report actual
produced counts, not config counts.

Fixture-based, no network, no ffmpeg, no real rendering: src.run.run_cmd
(the subprocess wrapper for narrate/music/video/scripts steps) and
src.run.run_qa are patched. Tests run in a temp cwd so data/ outputs
never touch the repo tree.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.run import build_format, main

NOOP_CMD = SimpleNamespace(stdout="mocked ok\n")


def _scripts_file(path, items):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(items, fh, indent=2)


def _one_script(rank=1, topic="Test Topic"):
    return {"rank": rank, "topic": topic, "text": "Some script text."}


class SilentSkipTests(unittest.TestCase):
    def setUp(self):
        self.saved = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        os.makedirs("data", exist_ok=True)

    def tearDown(self):
        os.chdir(self.saved)
        self.tmp.cleanup()

    def _log(self):
        return {"started_at": "2026-11-17T00:00:00+00:00", "steps": []}

    @patch("src.run.run_cmd", return_value=NOOP_CMD)
    @patch("src.run.run_qa", return_value=True)
    def test_missing_video_after_render_fails_loudly(self, _qa, _cmd):
        """(a) Render step mocked to produce no MP4: build_format must
        exit non-zero (SystemExit) and log the missing file path."""
        scripts = os.path.join(self.tmp.name, "scripts_short.json")
        _scripts_file(scripts, [_one_script()])
        log = self._log()
        args = SimpleNamespace(skip_video=False)
        with self.assertRaises(SystemExit) as ctx:
            build_format(log, "short", scripts, {}, "history mysteries", args)
        missing = os.path.join("data", "videos_short", "01-test-topic.mp4")
        self.assertIn(missing, str(ctx.exception))
        failed = [s for s in log["steps"] if s["status"] == "FAILED"]
        self.assertTrue(failed, "no FAILED step was logged for the missing video")
        self.assertTrue(any(missing in s["detail"] for s in failed),
                        "FAILED step does not name the missing video file")

    @patch("src.run.run_cmd", return_value=NOOP_CMD)
    @patch("src.run.run_qa", return_value=True)
    def test_skip_video_mode_still_skips_without_failing(self, _qa, _cmd):
        """--skip-video deliberately renders nothing, so there is no
        render step to fail: build_format returns no outputs, no raise."""
        scripts = os.path.join(self.tmp.name, "scripts_short.json")
        _scripts_file(scripts, [_one_script()])
        log = self._log()
        outputs, qa_reports = build_format(
            log, "short", scripts, {}, "history mysteries",
            SimpleNamespace(skip_video=True))
        self.assertEqual(outputs, [])
        self.assertEqual(qa_reports, [])

    def _stage_main_inputs(self):
        """Minimal inputs main() needs before build_format runs."""
        shutil.copy(os.path.join(ROOT, "config.yaml"),
                    os.path.join(self.tmp.name, "config.yaml"))
        top5 = [{"title": f"Topic {i}", "topic": f"topic {i}"}
                for i in (1, 2, 3)]
        with open("data/top5.json", "w", encoding="utf-8") as fh:
            json.dump({"candidates": top5}, fh, indent=2)
        _scripts_file("data/scripts_long.json", [_one_script(1, "Topic 1")])
        _scripts_file("data/scripts_shorts.json",
                      [_one_script(2, "Topic 2"), _one_script(3, "Topic 3")])

    @patch("src.run.run_cmd", return_value=NOOP_CMD)
    @patch("src.run.run_qa", return_value=True)
    def test_main_summary_reports_actual_counts_zero_produced(self, _qa, _cmd):
        """(b) With --skip-video (0 videos produced) the run succeeds but
        the summary must say 0 produced, not the config 1 long + 2 Shorts."""
        self._stage_main_inputs()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(
                main(["--niche", "history mysteries investigated with "
                      "modern tech", "--skip-video"]), 0)
        out = buf.getvalue()
        self.assertIn("Run complete: 0 long-form + 0 Shorts produced", out)
        with open("data/run_log.json", encoding="utf-8") as fh:
            run_log = json.load(fh)
        self.assertEqual(run_log["status"], "ok")
        self.assertEqual(run_log["videos_produced"], 0)
        self.assertEqual(run_log["long_videos_produced"], 0)
        self.assertEqual(run_log["shorts_produced"], 0)

    @patch("src.run.run_cmd", return_value=NOOP_CMD)
    @patch("src.run.run_qa", return_value=True)
    def test_main_exits_nonzero_when_render_produces_no_video(self, _qa, _cmd):
        """(a) end-to-end: a real render step (mocked, producing no MP4)
        makes main() raise SystemExit and records FAILED in run_log.json."""
        self._stage_main_inputs()
        with self.assertRaises(SystemExit):
            main(["--niche", "history mysteries investigated with "
                  "modern tech"])
        with open("data/run_log.json", encoding="utf-8") as fh:
            run_log = json.load(fh)
        self.assertEqual(run_log["status"], "FAILED")
        failed = [s for s in run_log["steps"] if s["status"] == "FAILED"]
        self.assertTrue(failed, "run_log has no FAILED step for the missing video")
        self.assertTrue(
            any("videos_long" in s["detail"] and s["detail"].endswith(".mp4")
                for s in failed),
            "FAILED step does not name the missing long-form video file")


if __name__ == "__main__":
    unittest.main()
