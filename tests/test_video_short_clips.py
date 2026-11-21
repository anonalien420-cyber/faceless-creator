"""Regression tests for short stock clips in build_video (Phase 2).

Real Pexels stock is often 4-10 s per clip while a pattern-interrupt
segment is ~9.5 s (60 s Short) or 25 s (long-form). Before this fix a
trim past the end of a short clip yielded a short segment and the
xfade chain collapsed the whole render to ~one segment: a 63.6 s
render with real stock (gears 8.0 s, museum 4.12 s, ...) came out
9.5 s, and QA rightly failed duration + visual-manifest integrity.
build_video now loops short/unknown-duration clips (-stream_loop)
so every segment is full-length.

Real-ffmpeg test (skips cleanly without ffmpeg). The 30 s render
takes ~1-2 min on this VM.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.video import build_video

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VISUALS = os.path.join(REPO_ROOT, "productions",
                       "antikythera-short-2026-11-15", "visuals")
V2 = os.path.join(REPO_ROOT, "productions",
                  "antikythera-short-2026-11-15-v2")


def _probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True,
        check=True, timeout=60)
    return float(out.stdout.strip())


class ShortClipRenderTests(unittest.TestCase):
    def test_shortest_clip_renders_full_duration(self):
        # museum.mp4 is 4.12 s -- far shorter than a ~10 s segment.
        # A 30 s render using ONLY that clip must still come out ~30 s
        # with real visuals throughout (looped), not ~10 s.
        import shutil
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not available")
        narration = os.path.join(V2, "mixed-audio.mp3")
        script = {"text": "A geared bronze machine that predicted "
                          "eclipses existed in the ancient world about "
                          "two thousand years ago. Sponge divers found "
                          "the wreck off Antikythera in 1900.",
                  "topic": "The 2,000-Year-Old Object That Shouldn't Exist",
                  "hook": "A geared bronze machine that predicted eclipses."}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "short-clip-30s.mp4")
            build_video(script, narration, out,
                        visuals=[os.path.join(VISUALS, "museum.mp4")],
                        duration=30.0, width=1080, height=1920,
                        normalize_loudness=False)
            self.assertTrue(os.path.exists(out))
            self.assertAlmostEqual(_probe_duration(out), 30.0, delta=1.0)
            with open(out + ".visuals.json", encoding="utf-8") as fh:
                manifest = json.load(fh)
            self.assertAlmostEqual(manifest["real_seconds"], 30.0, delta=1.0)
            self.assertEqual(manifest["gradient_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
