"""Regression tests for the loudness chain fix (2026-11-16).

The finished v2 Short measured -26.35 LUFS / -9.62 dBTP and still
passed QA 21/21 because nothing checked integrated loudness or true
peak on the finished file. These tests pin the fix:
- measure_loudness / loudness_ok on real fixtures
- normalize_loudness brings a quiet file to -14 LUFS / <= -1 dBTP
  on the MUXED output (headroom for AAC overshoot), keeping the
  video stream byte-identical
- the QA audio_loudness gate fails a too-quiet file and passes a
  normalized one (and run_qa auto-fixes loudness properly)
- build_video normalizes by default and leaves the raw render alone
  when asked not to

Fixture-based, no network. Real-ffmpeg tests skip cleanly without
ffmpeg; the burst fixture needs only the stdlib wave module.
"""
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import music, qa
from src.music import (TARGET_LUFS, TARGET_TP_DB, loudness_ok,
                       measure_loudness, normalize_loudness)
from src.video import build_video

HAS_FFMPEG = bool(shutil.which("ffmpeg"))


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {(result.stderr or '')[-500:]}")
    return result


def _write_quiet_mp4(path, seconds=3.0):
    """Tiny MP4: testsrc video + a quiet 440 Hz sine (~-26 LUFS)."""
    _run(["ffmpeg", "-y", "-v", "error",
          "-f", "lavfi", "-i",
          f"testsrc2=size=320x240:rate=30:duration={seconds}",
          "-f", "lavfi", "-i",
          f"sine=frequency=440:duration={seconds}",
          "-af", "volume=0.05",
          "-c:v", "libx264", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-shortest", path])


def _write_burst_wav(path, seconds=3.0, sr=24000):
    """Quiet tone with sparse loud transients: the real narration's
    crest-factor problem in miniature (integrated ~-24 LUFS, true
    peak ~-5 dBFS, ~19 dB crest). The tone carries the energy (like
    the voice); the brief 15 ms bursts carry the peaks (like
    plosives). A naive linear gain to -14 LUFS would push the peaks
    to about +5 dBTP, so the limiter must do real work — but unlike
    a burst-dominated signal the file IS normalizable, because the
    tone (not the capped peaks) carries the integrated level."""
    frames = int(seconds * sr)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        out = bytearray()
        for i in range(frames):
            t = i / sr
            sample = 0.08 * math.sin(2 * math.pi * 440 * t)
            for burst_at in (0.75, 2.25):
                if abs(t - burst_at) < 0.0075:
                    sample += 0.5 * math.sin(2 * math.pi * 880 * t)
            out += struct.pack("<h", int(max(-1, min(1, sample)) * 32767))
        fh.writeframes(bytes(out))


def _write_crest_mp4(path, seconds=3.0):
    """Tiny MP4 whose audio has the real narration's crest-factor
    problem: quiet overall, hot transient peaks."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "burst.wav")
        _write_burst_wav(wav, seconds)
        _run(["ffmpeg", "-y", "-v", "error",
              "-f", "lavfi", "-i",
              f"testsrc2=size=320x240:rate=30:duration={seconds}",
              "-i", wav,
              "-c:v", "libx264", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "128k", "-shortest", path])


def _video_stream_hash(path):
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "v.h264")
        _run(["ffmpeg", "-y", "-v", "error", "-i", path,
              "-map", "0:v", "-c", "copy", "-f", "h264", raw])
        with open(raw, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()


def _probe_duration(path):
    result = _run(["ffprobe", "-v", "quiet", "-print_format", "json",
                   "-show_format", path])
    return float(json.loads(result.stdout)["format"]["duration"])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class LoudnessMeasureTests(unittest.TestCase):
    def test_measure_loudness_reads_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mp4 = os.path.join(tmp, "quiet.mp4")
            _write_quiet_mp4(mp4)
            measured = measure_loudness(mp4)
            self.assertEqual(
                set(measured),
                {"input_i", "input_tp", "input_lra", "input_thresh"})
            # Quiet sine: clearly below the -14 LUFS target.
            self.assertLess(measured["input_i"], -20)
            self.assertLess(measured["input_tp"], -20)

    def test_measure_loudness_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            measure_loudness("/nonexistent/nope.mp4")

    def test_loudness_ok_boundaries(self):
        self.assertTrue(loudness_ok({"input_i": -14.0, "input_tp": -1.0})[0])
        self.assertTrue(loudness_ok({"input_i": -13.2, "input_tp": -1.5})[0])
        self.assertTrue(loudness_ok({"input_i": -15.0, "input_tp": -1.0})[0])
        # The v2 Short's measurement must fail.
        self.assertFalse(
            loudness_ok({"input_i": -26.35, "input_tp": -9.62})[0])
        # True peak over the cap fails even with LUFS on target.
        self.assertFalse(
            loudness_ok({"input_i": -14.0, "input_tp": -0.5})[0])
        # LUFS outside +/-1 fails even with TP fine.
        self.assertFalse(
            loudness_ok({"input_i": -15.5, "input_tp": -2.0})[0])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class NormalizeLoudnessTests(unittest.TestCase):
    def test_normalize_quiet_mp4_hits_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "quiet.mp4")
            out = os.path.join(tmp, "norm.mp4")
            _write_quiet_mp4(src)
            before_hash = _video_stream_hash(src)
            report = normalize_loudness(src, out)
            measured = report["output_measured"]
            ok, detail = loudness_ok(measured)
            self.assertTrue(ok, detail)
            self.assertEqual(_video_stream_hash(out), before_hash,
                             "video stream must be byte-identical; "
                             "only the audio may change")
            self.assertAlmostEqual(_probe_duration(out),
                                   _probe_duration(src), delta=0.1)
            self.assertLessEqual(len(report["attempts"]), 3)

    def test_normalize_crest_factor_fixture_holds_true_peak(self):
        # The headroom regression: a naive linear gain to -14 LUFS
        # would push this file's transient peaks to about +5 dBTP.
        # The limiter must hold the MUXED true peak at or under -1.
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "crest.mp4")
            out = os.path.join(tmp, "crest_norm.mp4")
            _write_crest_mp4(src)
            before = measure_loudness(src)
            self.assertLess(before["input_i"], -20)
            self.assertGreater(before["input_tp"], -10,
                               "fixture must actually have hot peaks")
            report = normalize_loudness(src, out)
            measured = report["output_measured"]
            ok, detail = loudness_ok(measured)
            self.assertTrue(ok, detail)
            # The limiter did real work: peaks stayed capped while
            # the integrated level came up to target.
            self.assertLessEqual(measured["input_tp"], -1.0)
            self.assertGreaterEqual(measured["input_i"], -15.0)

    def test_normalize_audio_only_mp3(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "burst.wav")
            _write_burst_wav(wav)
            src = os.path.join(tmp, "burst.mp3")
            _run(["ffmpeg", "-y", "-v", "error", "-i", wav,
                  "-c:a", "libmp3lame", "-b:a", "128k", src])
            out = os.path.join(tmp, "burst_norm.mp3")
            report = normalize_loudness(src, out)
            ok, detail = loudness_ok(report["output_measured"])
            self.assertTrue(ok, detail)

    def test_normalize_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                normalize_loudness("/nonexistent/nope.mp4",
                                   os.path.join(tmp, "out.mp4"))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class QaLoudnessGateTests(unittest.TestCase):
    def _loudness_check(self, video):
        checks, _ = qa.check(video)
        found = [c for c in checks if c["check"] == "audio_loudness"]
        self.assertEqual(len(found), 1, "audio_loudness check must exist")
        return found[0]

    def test_gate_fails_quiet_file(self):
        # The v2 scenario: mean -25.9 dB passed QA. A file that quiet
        # must now fail the loudness gate.
        with tempfile.TemporaryDirectory() as tmp:
            mp4 = os.path.join(tmp, "quiet.mp4")
            _write_quiet_mp4(mp4)
            check = self._loudness_check(mp4)
            self.assertEqual(check["status"], "fail")
            self.assertIn("LUFS", check["detail"])

    def test_gate_passes_normalized_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "quiet.mp4")
            norm = os.path.join(tmp, "norm.mp4")
            _write_quiet_mp4(src)
            normalize_loudness(src, norm)
            check = self._loudness_check(norm)
            self.assertEqual(check["status"], "pass", check["detail"])

    def test_run_qa_autofix_normalizes_quiet_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mp4 = os.path.join(tmp, "quiet.mp4")
            report_path = os.path.join(tmp, "qa_report.json")
            _write_quiet_mp4(mp4)
            # Overall QA still fails (320x240, no captions), but the
            # loudness auto-fix must have run and fixed the audio.
            ok = qa.run_qa(mp4, report_path=report_path, fmt="short")
            self.assertFalse(ok)
            with open(report_path, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertTrue(
                any("loudness normalized" in f
                    for f in report["fixes_applied"]),
                f"fixes: {report['fixes_applied']}")
            check = self._loudness_check(mp4)
            self.assertEqual(check["status"], "pass", check["detail"])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class BuildVideoLoudnessTests(unittest.TestCase):
    def test_build_video_normalizes_by_default(self):
        script = {"topic": "Loudness Test",
                  "text": "A short test narration for loudness."}
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.wav")
            _write_burst_wav(audio)
            out = os.path.join(tmp, "out.mp4")
            build_video(script, audio, out, visuals=[], duration=3.0)
            ok, detail = loudness_ok(measure_loudness(out))
            self.assertTrue(ok, detail)

    def test_build_video_normalize_false_keeps_raw_render(self):
        script = {"topic": "Loudness Test",
                  "text": "A short test narration for loudness."}
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.wav")
            _write_burst_wav(audio)
            out = os.path.join(tmp, "out.mp4")
            build_video(script, audio, out, visuals=[], duration=3.0,
                        normalize_loudness=False)
            measured = measure_loudness(out)
            self.assertLess(measured["input_i"], -20)


if __name__ == "__main__":
    unittest.main()
