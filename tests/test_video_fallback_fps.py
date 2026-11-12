"""Regression test for the gradient-fallback frame-rate bug (found
2026-11-12 during the end-to-end synthetic production run).

The lavfi ``gradients`` source defaults to 25 fps. The fallback render
path passed the source straight through with no ``fps`` filter, so
every gradient-fallback video came out at 25 fps while the QA gate
requires 30 fps — a guaranteed QA failure (and a run abort) whenever
no stock/ComfyUI visuals are available. The fix pins ``fps=30`` at the
head of the fallback filter chain, matching the visuals path.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from src.video import build_video


class GradientFallbackFpsTests(unittest.TestCase):
    def test_fallback_filter_chain_pins_30fps(self):
        script = {"topic": "Synthetic Pipeline Test",
                  "text": "SYNTHETIC TEST CLAIM: one sentence."}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.mp4")
            with patch("src.video._run_ffmpeg") as mocked:
                build_video(script, os.path.join(tmp, "narr.mp3"), out,
                            visuals=[], duration=5.0)
            cmd = mocked.call_args.args[0]
            vf = cmd[cmd.index("-vf") + 1]
            self.assertTrue(vf.startswith("fps=30,"),
                            "fallback -vf chain must start with fps=30, got: "
                            + vf[:80])

    def test_fallback_command_still_has_drawtext_overlay(self):
        # The fps pin must not displace the overlay filters.
        script = {"topic": "Synthetic Pipeline Test",
                  "text": "SYNTHETIC TEST CLAIM: one sentence."}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.mp4")
            with patch("src.video._run_ffmpeg") as mocked:
                build_video(script, os.path.join(tmp, "narr.mp3"), out,
                            visuals=[], duration=5.0)
            vf = mocked.call_args.args[0]
            vf = vf[vf.index("-vf") + 1]
            self.assertIn("drawtext=textfile=", vf)
            self.assertIn("ass=", vf)


if __name__ == "__main__":
    unittest.main()
