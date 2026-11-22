"""Narration fallback detection (Phase 3, item 3).

If narration generation falls back to a different engine/voice than
the configured Kokoro bm_george, the run must detect it: a loud
warning, a marker file (data/narration_fallback.json) so the
pipeline marks the run degraded, and — in strict mode
(config narrator_strict, or DEEP_SCAN_STRICT_NARRATION=1) — a hard
failure instead of shipping the wrong voice.
"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.narrate import (
    clear_narration_fallback,
    detect_narration_fallback,
    main as narrate_main,
    record_narration_fallback,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DetectFallbackTests(unittest.TestCase):
    def test_local_kokoro_configured_voice_is_not_a_fallback(self):
        result = detect_narration_fallback("kokoro (bm_george)", "local",
                                           "bm_george")
        self.assertFalse(result["fallback"])
        self.assertEqual(result["expected_engine"], "kokoro")
        self.assertEqual(result["expected_voice"], "bm_george")

    def test_local_edge_fallback_is_detected(self):
        result = detect_narration_fallback(
            "edge-tts (SSML prosody)", "local", "bm_george")
        self.assertTrue(result["fallback"])
        self.assertIn("bm_george", result["reason"])
        self.assertIn("edge-tts", result["reason"])

    def test_local_wrong_kokoro_voice_is_detected(self):
        # Kokoro silently substitutes af_heart for a non-Kokoro
        # config voice; a Kokoro render in the wrong voice is still
        # a fallback from the configured bm_george.
        result = detect_narration_fallback("kokoro (af_heart)", "local",
                                           "bm_george")
        self.assertTrue(result["fallback"])
        self.assertIn("af_heart", result["reason"])
        self.assertIn("bm_george", result["reason"])

    def test_local_non_kokoro_config_voice_expects_default(self):
        # A config voice that is not a Kokoro voice resolves to
        # af_heart inside narrate_kokoro; that is the expectation,
        # not a fallback.
        result = detect_narration_fallback("kokoro (af_heart)", "local",
                                           "en-US-AriaNeural")
        self.assertFalse(result["fallback"])
        self.assertEqual(result["expected_voice"], "af_heart")

    def test_free_edge_is_not_a_fallback(self):
        result = detect_narration_fallback(
            "edge-tts CLI (plain text, pause punctuation)", "free",
            "en-US-AriaNeural")
        self.assertFalse(result["fallback"])

    def test_free_pyttsx3_robotic_fallback_is_detected(self):
        result = detect_narration_fallback(
            "pyttsx3 (robotic fallback — install edge-tts for a "
            "natural voice)", "free", "en-US-AriaNeural")
        self.assertTrue(result["fallback"])
        self.assertIn("pyttsx3", result["reason"])

    def test_free_unknown_engine_is_detected(self):
        result = detect_narration_fallback("", "free", "en-US-AriaNeural")
        self.assertTrue(result["fallback"])

    def test_paid_elevenlabs_is_not_a_fallback(self):
        result = detect_narration_fallback(
            "elevenlabs (21m00Tcm4TlvDq8ikWAM)", "paid", "21m00Tcm4TlvDq8ikWAM")
        self.assertFalse(result["fallback"])

    def test_paid_edge_is_detected(self):
        result = detect_narration_fallback("edge-tts (SSML prosody)",
                                           "paid", "21m00Tcm4TlvDq8ikWAM")
        self.assertTrue(result["fallback"])


class FallbackMarkerTests(unittest.TestCase):
    def test_record_and_clear_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fallback.json")
            record_narration_fallback(
                {"topic": "T", "tier": "local", "voice": "bm_george",
                 "fallback": True, "expected_engine": "kokoro",
                 "expected_voice": "bm_george",
                 "used": "edge-tts (SSML prosody)",
                 "reason": "tier 'local' expects Kokoro"},
                path)
            record_narration_fallback(
                {"topic": "T2", "tier": "local", "voice": "bm_george",
                 "fallback": True, "expected_engine": "kokoro",
                 "expected_voice": "bm_george",
                 "used": "edge-tts (SSML prosody)",
                 "reason": "tier 'local' expects Kokoro"},
                path)
            with open(path, encoding="utf-8") as fh:
                entries = json.load(fh)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["topic"], "T")
            self.assertIn("at", entries[0])
            clear_narration_fallback(path)
            self.assertFalse(os.path.exists(path))


class _FakeEdgeCommunicate:
    """Stand-in for edge_tts.Communicate: save() writes a dummy file."""

    def __init__(self, ssml, voice):
        self.ssml = ssml
        self.voice = voice

    async def save(self, output):
        with open(output, "wb") as fh:
            fh.write(b"\0" * 2000)


def _stub_edge_and_break_kokoro():
    """sys.modules entries: working edge_tts, Kokoro that raises
    ImportError on use (so narrate.py falls back to Edge TTS)."""
    edge_mod = types.ModuleType("edge_tts")
    edge_mod.Communicate = _FakeEdgeCommunicate

    class _BrokenPipeline:
        def __init__(self, *args, **kwargs):
            raise ImportError("Kokoro not installed (test stub)")

    kokoro_mod = types.ModuleType("kokoro")
    kokoro_mod.KPipeline = _BrokenPipeline
    return {"edge_tts": edge_mod, "kokoro": kokoro_mod}


class _StubModules:
    """Replace only the named sys.modules entries, restoring exactly
    those entries afterwards. (unittest.mock.patch.dict(sys.modules)
    would clear the WHOLE dict on exit, dropping modules imported
    during the test — numpy/soundfile get unloaded that way and then
    fail to re-import with 'cannot load module more than once'.)"""

    _MISSING = object()

    def __init__(self, stubs):
        self.stubs = stubs
        self.saved = {}

    def __enter__(self):
        for key, value in self.stubs.items():
            self.saved[key] = sys.modules.get(key, self._MISSING)
            sys.modules[key] = value
        return self

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is self._MISSING:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
        return False


def _write_minimal_config(path, strict):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("narrator_voice: \"bm_george\"\n")
        fh.write("narrator_tier: \"local\"\n")
        fh.write("narrator_speed: 0.9\n")
        fh.write("narrator_pause_ms: 350\n")
        fh.write(f"narrator_strict: {'true' if strict else 'false'}\n")


class NarrateMainFallbackTests(unittest.TestCase):
    def _run_main(self, strict):
        """Run narrate main() in a temp cwd with Kokoro broken and
        Edge stubbed. Returns (returncode, marker_entries)."""
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                scripts_path = os.path.join(tmp, "scripts.json")
                with open(scripts_path, "w", encoding="utf-8") as fh:
                    json.dump([{"rank": 1, "topic": "Test topic",
                                "text": "A geared bronze machine that "
                                        "predicted eclipses."}], fh)
                config_path = os.path.join(tmp, "config.yaml")
                _write_minimal_config(config_path, strict)
                with _StubModules(_stub_edge_and_break_kokoro()):
                    code = narrate_main([
                        "--input", scripts_path,
                        "--outdir", os.path.join(tmp, "audio"),
                        "--config", config_path])
                marker = os.path.join(tmp, "data",
                                      "narration_fallback.json")
                entries = []
                if os.path.exists(marker):
                    with open(marker, encoding="utf-8") as fh:
                        entries = json.load(fh)
                return code, entries
            finally:
                os.chdir(old_cwd)

    def test_fallback_marks_run_degraded_without_strict(self):
        code, entries = self._run_main(strict=False)
        self.assertEqual(code, 0)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["fallback"])
        self.assertIn("edge-tts", entries[0]["used"])

    def test_fallback_fails_run_in_strict_mode(self):
        code, entries = self._run_main(strict=True)
        self.assertEqual(code, 1)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["fallback"])


if __name__ == "__main__":
    unittest.main()
