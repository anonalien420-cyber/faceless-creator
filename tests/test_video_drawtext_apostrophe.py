"""Regression test: apostrophes in drawtext prompts must not break ffmpeg.

Bug (daily workflow, render step, rc=234): main's src/video.py built
inline drawtext filters as ``drawtext=text='...'`` and escaped "'" as
``\\'``. ffmpeg's filtergraph parser unescapes one layer, so drawtext's
option parser saw a bare quote again and aborted the whole graph with
"No option name near ':font=DejaVu Sans...'" — every render with an
apostrophe prompt died. Shorts (10 s interrupt interval) only reach
prompt #1 ("The key part:") below ~30 s and so mostly escaped it;
long renders easily reach "Here's why it works:" and failed.

Fix: dynamic overlay text is written to a file and passed with
drawtext's ``textfile=`` option (plus ``expansion=none``), so neither
parser ever sees the text.

These tests run REAL ffmpeg renders — inspecting the filter string
cannot prove the filtergraph parses — and are skipped when ffmpeg or
ffprobe is not installed.
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
requires_ffmpeg = unittest.skipUnless(
    HAS_FFMPEG, "ffmpeg and ffprobe are required for the render regression")

# Small render: the bug is in filtergraph parsing, not in resolution.
WIDTH, HEIGHT, BITRATE = 320, 568, "400k"


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {(result.stderr or '')[-800:]}")
    return result


def _write_audio(path, seconds):
    """Synthetic narration stand-in (a sine tone)."""
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
          f"sine=frequency=440:duration={seconds}",
          "-c:a", "aac", "-b:a", "96k", path])


def _probe(path):
    result = _run(["ffprobe", "-v", "quiet", "-print_format", "json",
                   "-show_streams", "-show_format", path])
    info = json.loads(result.stdout)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    return video, audio, float(info["format"]["duration"])


class DrawtextFileTests(unittest.TestCase):
    """The helper that makes the fix work, without needing ffmpeg."""

    def test_textfile_round_trips_ffmpeg_special_characters(self):
        text = "Here's why it works: 100% of \"quotes\", \\slashes\\ and [x]"
        with tempfile.TemporaryDirectory() as directory:
            path = _write_drawtext_file(directory, "prompt_2", text)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), text)

    def test_generated_path_is_filter_escaped(self):
        self.assertEqual(_drawtext_path("/tmp/a:b.txt"), "/tmp/a\\:b.txt")
        self.assertEqual(_drawtext_path("C:\\temp\\x.txt"),
                         "C\\:\\\\temp\\\\x.txt")


@requires_ffmpeg
class ApostropheRenderRegressionTests(unittest.TestCase):
    def _render(self, directory, seconds, width, height):
        audio = os.path.join(directory, "narration.m4a")
        output = os.path.join(directory, "out.mp4")
        _write_audio(audio, seconds)
        script = {
            "text": ("The mechanism is a two thousand year old object that "
                     "should not exist. Here is why it works."),
            "topic": "the antikythera mechanism",
            "hook": "A two thousand year old computer.",
        }
        build_video(script, audio, output, visuals=None, duration=seconds,
                    bitrate=BITRATE, width=width, height=height)
        return output

    def test_apostrophe_prompt_render_no_longer_fails(self):
        """30 s vertical render that fires "Here's why it works:".

        Shorts use a 10 s pattern-interrupt interval, so 30 s gives
        chunk_count = 3 and the k=2 prompt is "Here's why it works:" —
        the exact text that failed with ffmpeg rc=234 before the fix.
        """
        with tempfile.TemporaryDirectory() as directory:
            output = self._render(directory, 30, WIDTH, HEIGHT)
            self.assertTrue(os.path.exists(output), "build_video wrote no file")
            video, audio, duration = _probe(output)
            self.assertEqual((video["width"], video["height"]),
                             (WIDTH, HEIGHT))
            self.assertEqual(video["codec_name"], "h264")
            self.assertEqual(len(audio), 1)
            self.assertEqual(audio[0]["codec_name"], "aac")
            self.assertAlmostEqual(duration, 30, delta=1.0)

    def test_apostrophe_end_card_and_title_render(self):
        """Apostrophes in the topic title and the end card render too."""
        with tempfile.TemporaryDirectory() as directory:
            audio = os.path.join(directory, "narration.m4a")
            output = os.path.join(directory, "out.mp4")
            _write_audio(audio, 12)
            build_video(
                {"text": "Short narration for the render test.",
                 "topic": "history's greatest hoax",
                 "hook": "Don't miss this."},
                audio, output, visuals=None, duration=12, bitrate=BITRATE,
                width=WIDTH, height=HEIGHT,
                end_card_text="Don't miss the next scan")
            self.assertTrue(os.path.exists(output))
            video, _audio, duration = _probe(output)
            self.assertEqual((video["width"], video["height"]),
                             (WIDTH, HEIGHT))
            self.assertAlmostEqual(duration, 12, delta=1.0)

    def test_textfile_path_is_filter_safe_for_spaces_and_parentheses(self):
        """A temp dir with spaces/parens (common on CI paths) still renders."""
        with tempfile.TemporaryDirectory() as base:
            directory = os.path.join(base, "deep scan (run 1)")
            os.makedirs(directory)
            output = self._render(directory, 30, WIDTH, HEIGHT)
            self.assertTrue(os.path.exists(output))


if __name__ == "__main__":
    unittest.main()
