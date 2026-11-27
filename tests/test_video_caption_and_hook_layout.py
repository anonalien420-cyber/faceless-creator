"""Regression tests for ASS captions and long hook overlays.

The static tests run without ffmpeg; render-level checks run when ffmpeg
(and its libass filter for caption rendering) is installed.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import video

WIDTH, HEIGHT = 320, 568
HOOK = "How does this ancient machine keep working after two thousand years?"
CAPTION = "Caption text stays clean on screen."
EVENT_FIELDS = [
    "Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR",
    "MarginV", "Effect", "Text",
]
HAS_FFMPEG = bool(shutil.which("ffmpeg"))


def _has_ass_filter():
    if not HAS_FFMPEG:
        return False
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return any(len(line.split()) > 1 and line.split()[1] == "ass"
               for line in result.stdout.splitlines())


HAS_LIBASS = _has_ass_filter()
requires_ffmpeg = unittest.skipUnless(
    HAS_FFMPEG, "ffmpeg is required for the render regression")
requires_libass = unittest.skipUnless(
    HAS_LIBASS, "ffmpeg with the libass filter is required for caption rendering")


def _render_ass_frame(ass_path):
    """Render one frame with the ASS file and return packed RGB pixels."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=black:s=320x568:r=1:d=1",
         "-vf", f"ass={video._drawtext_path(ass_path)}",
         "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
        capture_output=True, timeout=120, check=True)
    return result.stdout


def _write_audio(path, seconds):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}", "-c:a", "aac",
         "-b:a", "96k", path],
        capture_output=True, timeout=120, check=True)


def _frame_rgb(path, width, height):
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "1",
         "-i", path, "-frames:v", "1", "-pix_fmt", "rgb24",
         "-f", "rawvideo", "pipe:1"],
        capture_output=True, timeout=120, check=True)
    pixels = result.stdout
    if len(pixels) != width * height * 3:
        raise AssertionError(
            f"expected {width}x{height} RGB frame, received {len(pixels)} bytes")
    return pixels


class ASSCaptionRegressionTests(unittest.TestCase):
    def test_events_format_matches_dialogue_fields_and_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "captions.ass")
            video.make_ass(CAPTION, 2, path, width=WIDTH, height=HEIGHT,
                           fontsize=24)
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()

        events_start = lines.index("[Events]")
        format_fields = lines[events_start + 1].partition(":")[2].strip().split(", ")
        dialogue = next(line for line in lines[events_start + 2:]
                        if line.startswith("Dialogue:"))
        dialogue_fields = dialogue.partition(":")[2].strip().split(",", 9)

        self.assertEqual(format_fields, EVENT_FIELDS)
        self.assertEqual(len(dialogue_fields), len(EVENT_FIELDS))
        self.assertEqual(dialogue_fields[-1], CAPTION)

    @requires_libass
    def test_libass_render_has_no_stray_ass_fields_before_caption(self):
        """The generated caption pixels must equal a clean ASS reference."""
        with tempfile.TemporaryDirectory() as directory:
            generated = os.path.join(directory, "generated.ass")
            reference = os.path.join(directory, "reference.ass")
            video.make_ass(CAPTION, 2, generated, width=WIDTH, height=HEIGHT,
                           fontsize=24)
            reference_content = "\n".join([
                "[Script Info]",
                "ScriptType: v4.00+",
                f"PlayResX: {WIDTH}",
                f"PlayResY: {HEIGHT}",
                "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Alignment, MarginL, MarginR, MarginV, BorderStyle, Outline",
                "Style: Default,DejaVu Sans,24,&H00FFFFFF,&H80000000,-1,2,60,60,400,1,5",
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                f"Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,{CAPTION}",
            ])
            with open(reference, "w", encoding="utf-8") as handle:
                handle.write(reference_content)

            rendered = _render_ass_frame(generated)
            clean_reference = _render_ass_frame(reference)

        self.assertTrue(
            any(rendered[i] > 200 and rendered[i + 1] > 200 and rendered[i + 2] > 200
                for i in range(0, len(rendered), 3)),
            "libass rendered no visible caption")
        self.assertEqual(
            rendered, clean_reference,
            "caption pixels differ from clean text; ASS event fields may be visible")


class HookLayoutRegressionTests(unittest.TestCase):
    def test_long_hook_wraps_and_scales_to_fit_frame(self):
        self.assertGreater(len(HOOK), 60)
        wrapped, fontsize = video._fit_hook_text(HOOK, WIDTH, 54)
        side_margin = int(WIDTH * 0.05)
        max_chars = max(1, (WIDTH - 2 * side_margin - 4) // fontsize)

        self.assertEqual(" ".join(wrapped.split()), HOOK)
        self.assertGreater(wrapped.count("\n"), 0)
        self.assertLess(fontsize, 54)
        self.assertTrue(all(len(line) <= max_chars for line in wrapped.splitlines()))

    def test_build_video_passes_wrapped_hook_to_drawtext(self):
        """Keep the layout helper wired into build_video's actual filter."""
        with tempfile.TemporaryDirectory() as directory:
            captured_text = {}
            original_writer = video._write_drawtext_file

            def capture_textfile(temp_dir, name, text):
                captured_text[name] = text
                return original_writer(temp_dir, name, text)

            with mock.patch.object(video, "_require"), \
                    mock.patch.object(video, "resolve_visuals", return_value=([], [])), \
                    mock.patch.object(video, "_write_drawtext_file",
                                      side_effect=capture_textfile), \
                    mock.patch.object(video.subprocess, "run") as run:
                video.build_video(
                    {"text": "A short caption for the hook layout regression.",
                     "topic": "long hook layout", "hook": HOOK},
                    os.path.join(directory, "audio.m4a"),
                    os.path.join(directory, "out.mp4"), duration=6,
                    bitrate="400k", width=WIDTH, height=HEIGHT)

            command = run.call_args.args[0]
            filtergraph = command[command.index("-vf") + 1]

        expected_text, expected_fontsize = video._fit_hook_text(HOOK, WIDTH, 54)
        self.assertEqual(captured_text["hook"], expected_text)
        self.assertIn(f"fontsize={expected_fontsize}:", filtergraph)

    @requires_ffmpeg
    def test_long_hook_render_stays_inside_frame(self):
        """Render a 68-character hook and ensure its text is not edge-clipped."""
        with tempfile.TemporaryDirectory() as directory:
            audio = os.path.join(directory, "narration.m4a")
            output = os.path.join(directory, "out.mp4")
            _write_audio(audio, 6)
            video.build_video(
                {"text": "A short caption for the hook layout regression.",
                 "topic": "long hook layout", "hook": HOOK},
                audio, output, visuals=None, duration=6, bitrate="400k",
                width=WIDTH, height=HEIGHT)
            pixels = _frame_rgb(output, WIDTH, HEIGHT)

        hook_top = 200 + 72 + 20
        hook_bottom = HEIGHT - 60
        bright_x = []
        for y in range(hook_top, hook_bottom):
            for x in range(WIDTH):
                offset = (y * WIDTH + x) * 3
                red, green, blue = pixels[offset:offset + 3]
                if red > 200 and green > 200 and blue > 200:
                    bright_x.append(x)

        self.assertTrue(bright_x, "no hook text was visible in the rendered frame")
        self.assertGreater(min(bright_x), int(WIDTH * 0.02))
        self.assertLess(max(bright_x), int(WIDTH * 0.98))


if __name__ == "__main__":
    unittest.main()
