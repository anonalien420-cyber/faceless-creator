"""Regression tests for short stock clips in build_video (Phase 2).

Real Pexels stock is often 4-10 s per clip while a pattern-interrupt
segment is ~9.5 s (60 s Short) or 25 s (long-form). Before this fix a
trim past the end of a short clip yielded a short segment and the
xfade chain collapsed the whole render to ~one segment: a 63.6 s
render with real stock (gears 8.0 s, museum 4.12 s, ...) came out
9.5 s, and QA rightly failed duration + visual-manifest integrity.
build_video now loops short/unknown-duration clips (-stream_loop)
so every segment is full-length.

The production stock clips and mixed-audio.mp3 are NOT in the repo
(run #260: ffmpeg failed opening the production narration), so this
test synthesizes both inputs in tmp: a 4 s 1080x1920 clip standing
in for the 4.12 s museum stock clip, and a sine narration. The loop
path under test is identical.

Real-ffmpeg test (skips cleanly without ffmpeg). The 30 s render
takes ~1-2 min on this VM.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.video import build_video


def _probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True,
        check=True, timeout=60)
    return float(out.stdout.strip())


def _write_sine_mp3(path, seconds):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}", "-c:a", "libmp3lame",
         "-b:a", "128k", path],
        capture_output=True, text=True, check=True, timeout=300)


def _write_short_clip(path, seconds=4.0):
    # 1080x1920, 30 fps, shorter than one ~10 s segment: the clip
    # under test for the -stream_loop fix.
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"testsrc2=size=1080x1920:rate=30:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
        capture_output=True, text=True, check=True, timeout=300)


class ShortClipRenderTests(unittest.TestCase):
    def test_shortest_clip_renders_full_duration(self):
        # A 4 s clip is far shorter than a ~10 s segment. A 30 s
        # render using ONLY that clip must still come out ~30 s with
        # real visuals throughout (looped), not ~10 s.
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not available")
        script = {"text": "A geared bronze machine that predicted "
                          "eclipses existed in the ancient world about "
                          "two thousand years ago. Sponge divers found "
                          "the wreck off Antikythera in 1900.",
                  "topic": "The 2,000-Year-Old Object That Shouldn't Exist",
                  "hook": "A geared bronze machine that predicted eclipses."}
        with tempfile.TemporaryDirectory() as tmp:
            narration = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(narration, 35.0)
            clip = os.path.join(tmp, "short-clip.mp4")
            _write_short_clip(clip)
            out = os.path.join(tmp, "short-clip-30s.mp4")
            build_video(script, narration, out,
                        visuals=[clip],
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
