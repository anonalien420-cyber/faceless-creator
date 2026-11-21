"""Tests for the Phase 2 production transcription step (src/run.py).

The daily run must transcribe each mixed narration with faster-whisper
(small, word timestamps) and pass the timings to src/video.py — and
FAIL LOUDLY when transcription fails or hears nothing, never silently
rendering unsynced captions. The transcription itself reuses the
existing src.caption_treatments.get_word_timings helper (faster-whisper
via the tts_venv interpreter); these tests pin the run.py wrapper
(src.run.transcribe_narration) and the run -> video handoff.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.run import transcribe_narration  # noqa: E402
from src.video import _load_timings_for_script  # noqa: E402

NARRATION = os.path.join(
    ROOT, "productions", "antikythera-short-2026-11-15-v2",
    "narration-kokoro-bm_george-0.9.mp3")

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class TranscribeNarrationTests(unittest.TestCase):
    def test_writes_triples_json_and_returns_them(self):
        heard = [{"word": "A", "start": 0.0, "end": 0.4},
                 {"word": "geared", "start": 0.4, "end": 0.9}]
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "01-test.json")
            with patch("src.run.get_word_timings", return_value=heard):
                triples = transcribe_narration(
                    os.path.join(tmp, "narr.mp3"), out)
            self.assertEqual(triples, [[0.0, 0.4, "A"], [0.4, 0.9, "geared"]])
            with open(out, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), triples)

    def test_transcription_error_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.run.get_word_timings",
                       side_effect=RuntimeError("model blew up")):
                with self.assertRaises(SystemExit) as ctx:
                    transcribe_narration(
                        os.path.join(tmp, "narr.mp3"),
                        os.path.join(tmp, "01-test.json"))
            self.assertIn("Transcription FAILED", str(ctx.exception))
            self.assertFalse(os.path.exists(os.path.join(tmp, "01-test.json")))

    def test_empty_transcription_fails_loudly(self):
        # Whisper heard nothing (e.g. silent/corrupt audio): no words
        # must never become a silent fallback to unsynced captions.
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.run.get_word_timings", return_value=[]):
                with self.assertRaises(SystemExit) as ctx:
                    transcribe_narration(
                        os.path.join(tmp, "narr.mp3"),
                        os.path.join(tmp, "01-test.json"))
            self.assertIn("NO words", str(ctx.exception))

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
    @unittest.skipUnless(os.path.isfile(NARRATION),
                         "v2 Kokoro narration fixture not present")
    def test_real_transcription_small_model(self):
        """At least one test must use the REAL faster-whisper model
        (small) on a short real audio fixture — no mocks here."""
        with tempfile.TemporaryDirectory() as tmp:
            clip = os.path.join(tmp, "narr-8s.mp3")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", NARRATION,
                 "-t", "8", "-c", "copy", clip],
                check=True, timeout=120)
            out = os.path.join(tmp, "01-test.json")
            triples = transcribe_narration(clip, out, model="small")
            self.assertGreaterEqual(len(triples), 10,
                                    f"only {len(triples)} words heard in 8s")
            self.assertLess(triples[0][0], 0.5)
            prev_end = 0.0
            for start, end, word in triples:
                self.assertLessEqual(prev_end, start + 0.01)
                self.assertLess(start, end)
                self.assertLessEqual(end, 8.5)
                self.assertTrue(word.strip())
                prev_end = end
            with open(out, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), triples)


class TimingsDirResolutionTests(unittest.TestCase):
    def test_dir_file_wins_over_shared_timings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "01-test-topic.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([[0.0, 0.5, "hello"]], fh)
            script = {"rank": 1, "topic": "Test Topic", "text": "hello"}
            got = _load_timings_for_script(
                script, [(9.0, 9.5, "shared")], tmp, False)
            self.assertEqual(got, [(0.0, 0.5, "hello")])

    def test_missing_dir_file_with_require_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = {"rank": 1, "topic": "Test Topic", "text": "hello"}
            with self.assertRaises(SystemExit):
                _load_timings_for_script(script, None, tmp, True)

    def test_missing_dir_file_without_require_returns_none(self):
        # Dir given but no file for this script, and no --require flag:
        # legacy behaviour (None -> uniform chunking). Production
        # always passes --require-word-timings, so this path is
        # explicit non-production use only.
        with tempfile.TemporaryDirectory() as tmp:
            script = {"rank": 1, "topic": "Test Topic", "text": "hello"}
            shared = [(9.0, 9.5, "shared")]
            self.assertIsNone(
                _load_timings_for_script(script, shared, tmp, False))

    def test_no_dir_uses_shared_timings(self):
        script = {"rank": 1, "topic": "Test Topic", "text": "hello"}
        shared = [(9.0, 9.5, "shared")]
        self.assertEqual(
            _load_timings_for_script(script, shared, "", False), shared)


if __name__ == "__main__":
    unittest.main()
