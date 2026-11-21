"""Tests for the ASS filter-path escaping fix (F12) and the visuals
manifest writer (Phase 2).

F12: src/video.py built f"ass={ass_path}" unescaped, so an output path
containing ':', ',' or "'" broke the ffmpeg filtergraph. The fix is
escape_filter_arg() (backslash, single-quote, colon, comma, semicolon,
brackets). A real render whose output path contains a comma must
succeed; colon/quote paths are covered by real renders too (both are
legal Linux filename characters — a full render is cheap here, so no
unit-only cop-out for them).

Manifest contract (exact schema, written for BOTH render paths):
{"duration": float, "chunks": [{"start": float, "end": float,
"source": "real"|"gradient", "asset": str|null}, ...],
"real_seconds": float, "gradient_seconds": float}.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.video import build_video, escape_filter_arg  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEARS = os.path.join(ROOT, "productions", "antikythera-short-2026-11-15",
                     "visuals", "gears.mp4")
WRECK = os.path.join(ROOT, "productions", "antikythera-short-2026-11-15",
                     "visuals", "wreck.mp4")

SCRIPT = {"text": ("A geared bronze machine that predicted eclipses. "
                   "Sponge divers found the wreck."),
          "topic": "Test Topic", "hook": "A geared bronze machine."}


def _write_narration_audio(path, seconds=3.0):
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}", "-c:a", "aac",
         "-b:a", "128k", path], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")


def _probe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=60)
    return float(result.stdout.strip())


class EscapeHelperTests(unittest.TestCase):
    BS = "\\"

    def test_escapes_every_filtergraph_special(self):
        # Counts are exact and verified against real ffmpeg renders:
        # backslash 4x, quote 3x, colon 2x, comma/semicolon/brackets 1x.
        # (Double-escaping comma/semicolon/brackets BREAKS the render.)
        bs = self.BS
        self.assertEqual(
            escape_filter_arg("a:b,c;d[e]f'g\\h"),
            "a" + bs * 2 + ":b" + bs + ",c" + bs + ";d" + bs + "[e" + bs
            + "]f" + bs * 3 + "'g" + bs * 4 + "h")

    def test_plain_path_unchanged(self):
        self.assertEqual(escape_filter_arg("/tmp/out.mp4.ass"),
                         "/tmp/out.mp4.ass")

    def test_colon_and_quote_in_ass_path(self):
        bs = self.BS
        self.assertEqual(escape_filter_arg("/tmp/a:b/c'd.ass"),
                         "/tmp/a" + bs * 2 + ":b/c" + bs * 3 + "'d.ass")

    def test_backslash_needs_four(self):
        # A literal backslash passes through both parse levels, so
        # one becomes four — two would still fail the render.
        bs = self.BS
        self.assertEqual(escape_filter_arg("a\\b"), "a" + bs * 4 + "b")


def _manifest(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg and ffprobe are required")
class AssPathRenderTests(unittest.TestCase):
    def _render(self, tmp, name, seconds=3.0, visuals=None):
        audio = os.path.join(tmp, "narr.m4a")
        _write_narration_audio(audio, seconds=seconds)
        out = os.path.join(tmp, name)
        build_video(SCRIPT, audio, out, visuals=visuals,
                    duration=seconds, normalize_loudness=False)
        self.assertTrue(os.path.isfile(out), f"no output: {out}")
        return out

    def test_render_with_comma_in_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._render(tmp, "out,put.mp4")
            self.assertTrue(os.path.isfile(out + ".ass"))
            self.assertAlmostEqual(_probe_duration(out), 3.0, delta=0.6)

    def test_render_with_colon_in_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._render(tmp, "out:put.mp4")
            self.assertTrue(os.path.isfile(out + ".ass"))

    def test_render_with_quote_in_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._render(tmp, "out'put.mp4")
            self.assertTrue(os.path.isfile(out + ".ass"))

    def test_render_with_backslash_in_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._render(tmp, "out\\put.mp4")
            self.assertTrue(os.path.isfile(out + ".ass"))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg and ffprobe are required")
class VisualManifestTests(unittest.TestCase):
    def test_gradient_manifest_exact_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.m4a")
            _write_narration_audio(audio, seconds=3.0)
            out = os.path.join(tmp, "out.mp4")
            build_video(SCRIPT, audio, out, visuals=None, duration=3.0,
                        normalize_loudness=False)
            data = _manifest(out + ".visuals.json")
            self.assertEqual(set(data), {"duration", "chunks",
                                        "real_seconds", "gradient_seconds"})
            self.assertAlmostEqual(data["duration"], 3.0, places=2)
            self.assertEqual(len(data["chunks"]), 1)
            chunk = data["chunks"][0]
            self.assertEqual(set(chunk), {"start", "end", "source", "asset"})
            self.assertEqual(chunk["source"], "gradient")
            self.assertIsNone(chunk["asset"])
            self.assertAlmostEqual(chunk["start"], 0.0, places=2)
            self.assertAlmostEqual(chunk["end"], 3.0, places=2)
            self.assertEqual(data["real_seconds"], 0.0)
            self.assertAlmostEqual(data["gradient_seconds"], 3.0, places=2)

    @unittest.skipUnless(os.path.isfile(GEARS) and os.path.isfile(WRECK),
                         "production stock visuals not present")
    def test_real_visuals_manifest_exact_schema(self):
        # 12 s Short -> 2 pattern-interrupt chunks (10 s interval),
        # cycling gears then wreck; comma in the output path proves
        # the escaping fix on the visuals path too.
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.m4a")
            _write_narration_audio(audio, seconds=12.0)
            out = os.path.join(tmp, "out,put.mp4")
            build_video(SCRIPT, audio, out, visuals=[GEARS, WRECK],
                        duration=12.0, normalize_loudness=False)
            self.assertTrue(os.path.isfile(out))
            data = _manifest(out + ".visuals.json")
            self.assertEqual(set(data), {"duration", "chunks",
                                        "real_seconds", "gradient_seconds"})
            self.assertAlmostEqual(data["duration"], 12.0, places=2)
            self.assertEqual(len(data["chunks"]), 2)
            for chunk in data["chunks"]:
                self.assertEqual(set(chunk),
                                 {"start", "end", "source", "asset"})
                self.assertEqual(chunk["source"], "real")
                self.assertTrue(chunk["asset"])
            self.assertEqual(data["chunks"][0]["asset"], GEARS)
            self.assertEqual(data["chunks"][1]["asset"], WRECK)
            self.assertAlmostEqual(data["chunks"][0]["start"], 0.0, places=2)
            self.assertAlmostEqual(data["chunks"][0]["end"], 6.0, places=2)
            self.assertAlmostEqual(data["chunks"][1]["start"], 6.0, places=2)
            self.assertAlmostEqual(data["chunks"][1]["end"], 12.0, places=2)
            self.assertAlmostEqual(data["real_seconds"], 12.0, places=2)
            self.assertEqual(data["gradient_seconds"], 0.0)
            self.assertAlmostEqual(
                data["real_seconds"] + data["gradient_seconds"],
                data["duration"], places=2)


if __name__ == "__main__":
    unittest.main()
