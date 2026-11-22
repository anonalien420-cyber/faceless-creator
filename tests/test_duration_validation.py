"""Tests for Phase 3 item 4: duration validation (src/qa.py).

The rendered video duration must match the duration the Whisper word
timings imply (end of the last spoken word) within a small tolerance.
A truncated or over-long render must fail QA instead of passing
silently. Without word timings the check records "NOT verified"
instead of passing silently — the same convention as captions_timing.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.qa import (check, expected_duration_from_timings,
                    validate_duration)

HAS_FFMPEG = bool(shutil.which("ffmpeg"))


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


def _detail(checks, name):
    found = [c for c in checks if c["check"] == name]
    assert len(found) == 1
    return found[0]["detail"]


class ExpectedDurationTests(unittest.TestCase):
    def test_last_word_end_from_triples(self):
        timings = [(0.0, 1.2, "the"), (1.3, 4.5, "device"), (4.6, 62.36, "sea")]
        self.assertAlmostEqual(expected_duration_from_timings(timings), 62.36)

    def test_empty_timings_is_none(self):
        self.assertIsNone(expected_duration_from_timings([]))
        self.assertIsNone(expected_duration_from_timings(None))

    def test_malformed_entries_are_none(self):
        self.assertIsNone(expected_duration_from_timings([("a", "b")]))

    def test_real_fixture_last_word(self):
        fixture = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tests", "fixtures", "antikythera-words.json")
        with open(fixture, encoding="utf-8") as fh:
            data = json.load(fh)
        # Fixture is dict-shaped; normalise through the loader.
        from src.caption_validation import load_word_timings
        timings = load_word_timings(fixture)
        self.assertAlmostEqual(expected_duration_from_timings(timings),
                               62.36, places=1)


class ValidateDurationTests(unittest.TestCase):
    def test_within_tolerance_passes(self):
        ok, _ = validate_duration(63.6, 62.36, tolerance=2.0)
        self.assertTrue(ok)

    def test_truncated_fails(self):
        # The Phase 2 xfade collapse: 63.6 s in, 9.5 s out.
        ok, detail = validate_duration(9.5, 62.36, tolerance=2.0)
        self.assertFalse(ok)
        self.assertIn("9.5", detail)

    def test_overlong_fails(self):
        ok, _ = validate_duration(70.0, 62.36, tolerance=2.0)
        self.assertFalse(ok)

    def test_boundary_is_inclusive(self):
        ok, _ = validate_duration(64.36, 62.36, tolerance=2.0)
        self.assertTrue(ok)

    def test_no_expected_is_not_verified_not_failed(self):
        ok, detail = validate_duration(63.6, None, tolerance=2.0)
        self.assertTrue(ok)
        self.assertIn("not verified", detail.lower())


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class DurationCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _timings_file(self, last_end):
        path = os.path.join(self.tmp, "words.json")
        words = [{"word": "the", "start": 0.0, "end": 1.0},
                 {"word": "device", "start": 1.1, "end": last_end}]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(words, fh)
        return path

    def _video(self, seconds):
        audio = os.path.join(self.tmp, "narr.mp3")
        video = os.path.join(self.tmp, "out.mp4")
        _write_sine_mp3(audio, seconds)
        _write_test_video(video, seconds, audio)
        return video, audio

    def test_matching_duration_passes(self):
        video, audio = self._video(12.0)
        checks, _ = check(video, narration=audio,
                          word_timings_path=self._timings_file(11.5))
        self.assertEqual(_status(checks, "duration_matches_expected"), "pass")

    def test_truncated_video_fails(self):
        video, audio = self._video(6.0)
        checks, _ = check(video, narration=audio,
                          word_timings_path=self._timings_file(11.5))
        self.assertEqual(_status(checks, "duration_matches_expected"), "fail")
        self.assertIn("6.0", _detail(checks, "duration_matches_expected"))

    def test_overlong_video_fails(self):
        video, audio = self._video(20.0)
        checks, _ = check(video, narration=audio,
                          word_timings_path=self._timings_file(11.5))
        self.assertEqual(_status(checks, "duration_matches_expected"), "fail")

    def test_no_timings_records_not_verified(self):
        video, audio = self._video(12.0)
        checks, _ = check(video, narration=audio)
        self.assertEqual(_status(checks, "duration_matches_expected"), "pass")
        self.assertIn("NOT verified",
                      _detail(checks, "duration_matches_expected"))

    def test_unloadable_timings_file_fails(self):
        video, audio = self._video(12.0)
        missing = os.path.join(self.tmp, "no-such-words.json")
        checks, _ = check(video, narration=audio,
                          word_timings_path=missing)
        self.assertEqual(_status(checks, "duration_matches_expected"), "fail")


if __name__ == "__main__":
    unittest.main()
