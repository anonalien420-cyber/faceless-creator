"""Regression tests for the QA visual-manifest checks (F3, Phase 2 Worker B).

A render with zero real visuals used to pass QA 22/22: the gradient
fallback only print()ed and run_qa had no "real visuals used" check.
These tests pin the replacement -- real_visuals_present and
visual_coverage, each reported as its own QA check, reading the
<video>.visuals.json manifest build_video writes next to every render:

  {"duration": float,
   "chunks": [{"start": float, "end": float,
               "source": "real"|"gradient", "asset": str|null}, ...],
   "real_seconds": float, "gradient_seconds": float}

- missing manifest -> both visual checks FAIL (cannot verify)
- gradient-only render (visuals=[]) -> real_visuals_present FAILS
- real visuals spanning the duration, gradient within tolerance
  -> both visual checks PASS
- large gradient-only middle segment -> visual_coverage FAILS
  (while real_visuals_present still passes: some real visuals exist)
- malformed manifest -> both visual checks FAIL

Gradient tolerance rule: gradient_seconds must be <= max(2.0 s,
5% of the video duration).

The gradient-only test uses a real build_video render with
visuals=[] through the real run_qa path. The real-visuals PASS test
uses a real build_video render with local stock visuals
(wreck.mp4/gears.mp4 from the v2 production) plus a fixture manifest
-- build_video does not write .visuals.json yet in this tree (the
pipeline worker owns that writer), so the manifest here is a
fixture proving the QA READER side; the render itself is real.

Fixture-based, no network. Real-ffmpeg tests skip cleanly without
ffmpeg.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import qa
from src.caption_validation import check_visual_manifest, load_visual_manifest
from src.video import build_video

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2_VISUALS = os.path.join(REPO_ROOT, "productions",
                          "antikythera-short-2026-11-15-v2", "visuals")


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {(result.stderr or '')[-500:]}")
    return result


def _write_sine_mp3(path, seconds):
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
          f"sine=frequency=440:duration={seconds}", "-c:a", "libmp3lame",
          "-b:a", "128k", path])


def _write_test_video(path, seconds, audio):
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
          f"testsrc2=size=320x240:rate=30:duration={seconds}",
          "-i", audio, "-c:v", "libx264", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-shortest", path])


def _status(checks, name):
    found = [c for c in checks if c["check"] == name]
    assert len(found) == 1, f"check {name} must appear exactly once: {checks}"
    return found[0]["status"]


def _manifest(duration, chunks):
    real = sum(e - s for s, e, src in chunks if src == "real")
    gradient = sum(e - s for s, e, src in chunks if src == "gradient")
    return {"duration": float(duration),
            "chunks": [{"start": s, "end": e, "source": src,
                        "asset": ("clip.mp4" if src == "real" else None)}
                       for s, e, src in chunks],
            "real_seconds": float(real),
            "gradient_seconds": float(gradient)}


def _write_manifest(video, manifest):
    path = video + ".visuals.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return path


class VisualManifestHelperTests(unittest.TestCase):
    """Pure-helper tests for the manifest rules (fast, no ffmpeg)."""

    def test_gradient_tolerance_rule(self):
        # 12 s video: tolerance is max(2.0, 0.6) = 2.0 s.
        _, _, ok, detail = check_visual_manifest(
            _manifest(12.0, [(0.0, 10.0, "real"), (10.0, 12.0, "gradient")]),
            video_duration=12.0)
        self.assertTrue(ok, detail)
        self.assertIn("max(2.0s, 5% of 12.0s) = 2.00s", detail)
        # 60 s video: tolerance is max(2.0, 3.0) = 3.0 s.
        _, _, ok, _ = check_visual_manifest(
            _manifest(60.0, [(0.0, 57.0, "real"), (57.0, 60.0, "gradient")]),
            video_duration=60.0)
        self.assertTrue(ok)
        _, _, ok, detail = check_visual_manifest(
            _manifest(60.0, [(0.0, 56.0, "real"), (56.0, 60.0, "gradient")]),
            video_duration=60.0)
        self.assertFalse(ok, detail)
        self.assertIn("exceeds", detail)

    def test_totals_must_agree_with_chunks(self):
        bad = _manifest(12.0, [(0.0, 12.0, "real")])
        bad["real_seconds"] = 6.0  # chunks say 12 s real
        real_ok, _, cov_ok, detail = check_visual_manifest(
            bad, video_duration=12.0)
        self.assertFalse(real_ok, detail)
        self.assertFalse(cov_ok, detail)
        self.assertIn("disagrees with chunk sum", detail)

    def test_unknown_chunk_source_is_schema_error(self):
        bad = _manifest(12.0, [(0.0, 12.0, "real")])
        bad["chunks"][0]["source"] = "stock"
        with self.assertRaises(ValueError):
            load_visual_manifest_from_dict(bad)

    def test_missing_key_is_schema_error(self):
        bad = _manifest(12.0, [(0.0, 12.0, "real")])
        del bad["gradient_seconds"]
        with self.assertRaises(ValueError):
            load_visual_manifest_from_dict(bad)


def load_visual_manifest_from_dict(manifest):
    """Validate an already-loaded manifest dict via the file loader."""
    with tempfile.NamedTemporaryFile("w", suffix=".json",
                                     delete=False) as fh:
        json.dump(manifest, fh)
        path = fh.name
    try:
        return load_visual_manifest(path)
    finally:
        os.unlink(path)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class QaVisualCheckTests(unittest.TestCase):
    """Tests through the real qa.check()/run_qa() path."""

    def test_missing_manifest_fails_visual_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 6.0)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 6.0, audio)
            checks, _ = qa.check(video, narration=audio, fmt="short")
            self.assertEqual(_status(checks, "real_visuals_present"), "fail")
            self.assertEqual(_status(checks, "visual_coverage"), "fail")

    def test_real_visuals_manifest_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 12.0)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 12.0, audio)
            _write_manifest(video, _manifest(
                12.0, [(0.0, 11.5, "real"), (11.5, 12.0, "gradient")]))
            checks, _ = qa.check(video, narration=audio, fmt="short")
            self.assertEqual(_status(checks, "real_visuals_present"), "pass")
            self.assertEqual(_status(checks, "visual_coverage"), "pass")

    def test_large_gradient_middle_fails_coverage_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 12.0)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 12.0, audio)
            _write_manifest(video, _manifest(
                12.0, [(0.0, 3.0, "real"), (3.0, 9.0, "gradient"),
                       (9.0, 12.0, "real")]))
            checks, _ = qa.check(video, narration=audio, fmt="short")
            # Some real visuals exist, so presence passes...
            self.assertEqual(_status(checks, "real_visuals_present"), "pass")
            # ...but 6 s of gradient on a 12 s video exceeds the
            # max(2.0 s, 5%) = 2.0 s tolerance.
            self.assertEqual(_status(checks, "visual_coverage"), "fail")

    def test_malformed_manifest_fails_visual_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 6.0)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 6.0, audio)
            path = video + ".visuals.json"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"duration": 6.0, "chunks": []}, fh)
            checks, _ = qa.check(video, narration=audio, fmt="short")
            self.assertEqual(_status(checks, "real_visuals_present"), "fail")
            self.assertEqual(_status(checks, "visual_coverage"), "fail")

    def test_gradient_only_render_fails_real_visuals(self):
        # Real render with visuals=[] through the real run_qa path.
        script = {"text": "A short test narration for the visual check.",
                  "topic": "Visual Test"}
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.wav")
            _write_sine_mp3(audio, 3.0)
            video = os.path.join(tmp, "out.mp4")
            build_video(script, audio, video, visuals=[], duration=3.0)
            # No manifest exists (writer not landed yet): fail-closed.
            report = os.path.join(tmp, "qa_report.json")
            ok = qa.run_qa(video, narration=audio,
                           script_text=script["text"],
                           report_path=report, fmt="short")
            self.assertFalse(ok)
            with open(report, encoding="utf-8") as fh:
                data = json.load(fh)
            by_name = {c["check"]: c for c in data["checks"]}
            self.assertEqual(by_name["real_visuals_present"]["status"], "fail")
            # And with an explicit gradient-only manifest it fails
            # for the substantive reason, not just the missing file.
            _write_manifest(video, _manifest(
                3.0, [(0.0, 3.0, "gradient")]))
            checks, _ = qa.check(video, narration=audio,
                                 script_text=script["text"], fmt="short")
            self.assertEqual(_status(checks, "real_visuals_present"), "fail")
            self.assertIn("real_seconds == 0",
                          [c for c in checks
                           if c["check"] == "real_visuals_present"][0]["detail"])
            self.assertEqual(_status(checks, "visual_coverage"), "fail")

    def test_real_visuals_render_passes_visual_checks(self):
        # Real render with local stock visuals (wreck/gears from the
        # v2 production) + a fixture manifest (the writer is not
        # landed yet, so the manifest is a fixture; the render is
        # real). 10 s, one pattern-interrupt chunk.
        script_text = ("A geared bronze machine that predicted eclipses "
                       "existed in the ancient world")
        script = {"text": script_text,
                  "topic": "The 2,000-Year-Old Object That Shouldn't Exist"}
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 10.0)
            video = os.path.join(tmp, "out.mp4")
            build_video(script, audio, video,
                        visuals=[os.path.join(V2_VISUALS, "wreck.mp4"),
                                 os.path.join(V2_VISUALS, "gears.mp4")],
                        duration=10.0)
            _write_manifest(video, _manifest(
                10.0, [(0.0, 10.0, "real")]))
            checks, _ = qa.check(video, narration=audio,
                                 script_text=script_text, fmt="short")
            self.assertEqual(_status(checks, "real_visuals_present"), "pass")
            self.assertEqual(_status(checks, "visual_coverage"), "pass")


if __name__ == "__main__":
    unittest.main()
