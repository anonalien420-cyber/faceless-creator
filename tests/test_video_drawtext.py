"""Drawtext regression tests (Nov 16 daily-run failure, RC-1).

Main's src/video.py built inline drawtext filters with
_escape_drawtext() ("'" -> "\\'"), which terminates the quoted
filter value: ffmpeg rejected the filtergraph with rc=234 whenever
a prompt containing an apostrophe fired. That happens iff
chunk_count >= 3 (long-form: duration > 50 s), so every real long
failed deterministically. The branch reads all dynamic text from
files (drawtext=textfile=...:expansion=none).

The regression test below renders a REAL 60 s video through
build_video() — filter-string inspection alone cannot prove the
filtergraph parses — and probes the output with ffprobe.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.video import _drawtext_path, _write_drawtext_file, build_video

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {(result.stderr or '')[-500:]}")
    return result


def _write_narration_audio(path, seconds=60.0):
    """Synthetic 60 s narration stand-in (440 Hz sine)."""
    _run(["ffmpeg", "-y", "-v", "error",
          "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
          "-c:a", "aac", "-b:a", "128k", path])


def _probe(path):
    result = _run(["ffprobe", "-v", "quiet", "-print_format", "json",
                   "-show_streams", "-show_format", path])
    info = json.loads(result.stdout)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    return video, audio, float(info["format"]["duration"])


class DrawtextFileTests(unittest.TestCase):
    def test_textfile_preserves_ffmpeg_special_characters(self):
        text = """Here's 100%: history, "quotes", \slashes\ and [brackets]"""
        with tempfile.TemporaryDirectory() as directory:
            path = _write_drawtext_file(directory, "fixture", text)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), text)

    def test_generated_textfile_path_is_filter_escaped(self):
        self.assertEqual(_drawtext_path(r"C:\temp\file.txt"),
                         r"C\:\\temp\\file.txt")
        self.assertEqual(_drawtext_path("/tmp/a:b.txt"), "/tmp/a\\:b.txt")


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg and ffprobe are required")
class ApostropheRegressionTests(unittest.TestCase):
    def test_sixty_second_long_form_with_apostrophe_prompts_renders(self):
        """60 s long-form (1920x1080) through build_video().

        Long-form pattern-interrupt interval is 25 s, so a 60 s
        render has chunk_count = ceil(60/25) = 3 and fires prompts
        at k=1 ("The key part:") and k=2 ("Here's why it works:").
        The k=2 prompt is the exact Nov 16 failure: on main's inline
        drawtext=text='...' construction ffmpeg died with rc=234
        ("No option name near ':font=DejaVu Sans...'"). The branch
        must produce a valid 1920x1080 / 30 fps MP4 instead.

        normalize_loudness=False: the regression under test is
        filtergraph parsing, not the loudness chain (covered by
        tests/test_loudness.py); skipping loudnorm keeps this test
        CI-fast. Visuals are None on purpose — the gradient
        fallback is the path the Nov 16 repro exercised.
        """
        with tempfile.TemporaryDirectory() as directory:
            audio = os.path.join(directory, "narration.m4a")
            _write_narration_audio(audio, seconds=60.0)
            output = os.path.join(directory, "out.mp4")
            script = {
                "text": ("The Antikythera mechanism is a two thousand "
                         "year old object that should not exist. Here is "
                         "why it works and what it means for history."),
                "topic": "the antikythera mechanism",
                "hook": "A two thousand year old computer was found "
                        "in a shipwreck.",
            }
            build_video(script, audio, output, visuals=None,
                        width=1920, height=1080,
                        normalize_loudness=False)
            self.assertTrue(os.path.exists(output),
                            "build_video produced no output file")
            video, audio_streams, duration = _probe(output)
            self.assertEqual(video["width"], 1920)
            self.assertEqual(video["height"], 1080)
            self.assertEqual(video["codec_name"], "h264")
            num, den = (int(x) for x in
                        video["r_frame_rate"].split("/"))
            self.assertAlmostEqual(num / den, 30.0, places=1)
            # -shortest + 60 s of audio: allow a frame of slack.
            self.assertAlmostEqual(duration, 60.0, delta=1.0)
            self.assertEqual(len(audio_streams), 1)
            self.assertEqual(audio_streams[0]["codec_name"], "aac")

    def test_short_render_below_chunk_threshold_still_renders(self):
        """20 s long-form (chunk_count=1, no prompt drawtexts) renders.

        Control case: this input succeeded even on main, so it pins
        the baseline rather than the fix.
        """
        with tempfile.TemporaryDirectory() as directory:
            audio = os.path.join(directory, "narration.m4a")
            _write_narration_audio(audio, seconds=20.0)
            output = os.path.join(directory, "out.mp4")
            script = {
                "text": "A short check of the mechanism and its gears.",
                "topic": "the antikythera mechanism",
                "hook": "A two thousand year old computer.",
            }
            build_video(script, audio, output, visuals=None,
                        width=1920, height=1080,
                        normalize_loudness=False)
            video, _audio, duration = _probe(output)
            self.assertEqual((video["width"], video["height"]),
                             (1920, 1080))
            self.assertAlmostEqual(duration, 20.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
