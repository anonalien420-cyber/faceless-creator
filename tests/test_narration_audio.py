"""Tests for narration + music-bed safeguards (src/narrate.py, src/music.py).

Stdlib-only (unittest). Kokoro is NOT required: the Kokoro-voice tests
install stub ``kokoro`` / ``soundfile`` / ``numpy`` modules into
``sys.modules`` so the voice-name gate, speed pass-through and language
selection in ``narrate_kokoro`` can be checked without the real package.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import music, narrate
from src.config import load_config

BRANCH_ROOT = os.path.join(os.path.dirname(__file__), "..")


def write_wav(path, seconds=1.0, sample_rate=24000):
    """Write a real (silent) wav file >= 1000 bytes with duration > 0."""
    frames = int(seconds * sample_rate)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(b"\x00\x00" * frames)


# ---------------------------------------------------------------- narrate
class HumanizeTests(unittest.TestCase):
    def test_hook_emphasised_and_rate_matches_speed(self):
        ssml, plain = narrate.humanize_text(
            "In 1917, two schoolgirls photographed fairies. The truth stayed "
            "hidden for years. One photograph remained.",
            pause_ms=350, speed=0.9)
        self.assertIn('<emphasis level="strong">In 1917,', ssml)
        self.assertIn('rate="90%"', ssml)
        # Sentence-end break between 2nd and 3rd sentences (mid-body).
        self.assertIn('<break time="350ms"/>', ssml)
        self.assertIn('<break time="175ms"/>', ssml)  # comma pause = half

    def test_speed_1_gives_rate_100(self):
        ssml, _ = narrate.humanize_text("One sentence here.", speed=1.0)
        self.assertIn('rate="100%"', ssml)

    def test_plain_version_adds_pause_punctuation(self):
        _, plain = narrate.humanize_text("Hello, world. Goodbye, world.")
        self.assertIn(", ... ", plain)
        self.assertIn(". ... ", plain)

    def test_slug(self):
        self.assertEqual(narrate.slug("The Cottingley Fairies!"), "the-cottingley-fairies")
        self.assertEqual(narrate.slug(""), "script")


class CheckAudioTests(unittest.TestCase):
    def test_missing_file_fails(self):
        self.assertFalse(narrate._check_audio("/tmp/does-not-exist-xyz.wav", "x"))

    def test_tiny_file_fails(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            fh.write(b"x" * 10)
            path = fh.name
        try:
            self.assertFalse(narrate._check_audio(path, "x"))
        finally:
            os.unlink(path)

    def test_valid_wav_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ok.wav")
            write_wav(path, seconds=1.0)
            self.assertTrue(narrate._check_audio(path, "x"))


class FakePipeline:
    """Stand-in for kokoro.KPipeline: records lang/voice/speed, yields audio."""
    instances = []
    audio_chunks = [[0.1, -0.1, 0.2, 0.0]]

    def __init__(self, lang_code=None):
        self.lang_code = lang_code
        self.calls = []
        FakePipeline.instances.append(self)

    def __call__(self, text, voice=None, speed=None):
        self.calls.append({"text": text, "voice": voice, "speed": speed})
        for chunk in self.audio_chunks:
            yield ("", "", chunk)


def _install_kokoro_stubs():
    kokoro = types.ModuleType("kokoro")
    kokoro.KPipeline = FakePipeline
    soundfile = types.ModuleType("soundfile")

    def fake_write(path, data, samplerate):
        # Write a real wav so _check_audio passes; content is irrelevant.
        write_wav(path, seconds=1.0, sample_rate=samplerate)

    soundfile.write = fake_write
    numpy = types.ModuleType("numpy")

    def fake_concatenate(chunks):
        out = []
        for chunk in chunks:
            out.extend(chunk)
        return out

    numpy.concatenate = fake_concatenate
    sys.modules["kokoro"] = kokoro
    sys.modules["soundfile"] = soundfile
    sys.modules["numpy"] = numpy


class KokoroVoiceGateTests(unittest.TestCase):
    def setUp(self):
        FakePipeline.instances = []
        FakePipeline.audio_chunks = [[0.1, -0.1, 0.2, 0.0]]
        self._saved = {name: sys.modules.get(name)
                       for name in ("kokoro", "soundfile", "numpy")}
        _install_kokoro_stubs()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def tearDown(self):
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def _out(self):
        return os.path.join(self.tmp.name, "out.wav")

    def test_bm_george_passes_through_with_british_pipeline(self):
        used = narrate.narrate_kokoro("Hello world.", "bm_george", self._out(), 0.9)
        self.assertEqual(used, "kokoro (bm_george)")
        pipe = FakePipeline.instances[-1]
        self.assertEqual(pipe.lang_code, "b")  # British voice -> British pipeline
        self.assertEqual(pipe.calls[0]["voice"], "bm_george")
        self.assertEqual(pipe.calls[0]["speed"], 0.9)

    def test_american_voice_uses_american_pipeline(self):
        used = narrate.narrate_kokoro("Hello world.", "af_heart", self._out(), 1.0)
        self.assertEqual(used, "kokoro (af_heart)")
        self.assertEqual(FakePipeline.instances[-1].lang_code, "a")

    def test_non_kokoro_voice_falls_back_to_af_heart(self):
        used = narrate.narrate_kokoro("Hello world.", "en-US-ChristopherNeural",
                                      self._out(), 1.0)
        self.assertEqual(used, "kokoro (af_heart)")
        self.assertEqual(FakePipeline.instances[-1].calls[0]["voice"], "af_heart")
        self.assertEqual(FakePipeline.instances[-1].lang_code, "a")

    def test_empty_audio_raises_loudly(self):
        FakePipeline.audio_chunks = []
        with self.assertRaises(RuntimeError):
            narrate.narrate_kokoro("Hello world.", "bm_george", self._out(), 0.9)


class LocalTierFallbackTests(unittest.TestCase):
    """Tier 'local' + missing Kokoro must warn and fall back to Edge;
    a Kokoro runtime failure must fail loudly, never silently downgrade."""

    def _run_main(self, kokoro_side_effect):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = os.path.join(tmp, "scripts.json")
            with open(scripts, "w", encoding="utf-8") as fh:
                json.dump([{"rank": 1, "topic": "Test",
                            "text": "Hello world. This is a test."}], fh)
            config = os.path.join(tmp, "config.yaml")
            with open(config, "w", encoding="utf-8") as fh:
                fh.write('narrator_voice: "bm_george"\n'
                         'narrator_tier: "local"\n'
                         'narrator_speed: 0.9\n'
                         'narrator_pause_ms: 350\n')
            outdir = os.path.join(tmp, "audio")

            def fake_edge(text, voice, output, ssml, speed):
                write_wav(output, seconds=1.0)
                return "edge-tts (stub)"

            err = io.StringIO()
            with contextlib.redirect_stderr(err), \
                    patch.object(narrate, "narrate_kokoro",
                                 side_effect=kokoro_side_effect), \
                    patch.object(narrate, "narrate_edge",
                                 side_effect=fake_edge) as edge, \
                    patch.object(narrate, "append_run_log"):
                rc = narrate.main(["--input", scripts, "--outdir", outdir,
                                   "--config", config])
            return rc, err.getvalue(), edge

    def test_missing_kokoro_warns_and_falls_back_to_edge(self):
        rc, stderr, edge = self._run_main(ImportError("No module named 'kokoro'"))
        self.assertEqual(rc, 0)
        self.assertIn("WARNING: Kokoro not installed", stderr)
        self.assertIn("falling back to Edge TTS", stderr)
        self.assertEqual(edge.call_count, 1)

    def test_kokoro_runtime_failure_fails_loudly_without_edge(self):
        rc, stderr, edge = self._run_main(RuntimeError("Kokoro model failed"))
        self.assertEqual(rc, 1)
        self.assertEqual(edge.call_count, 0)  # no silent downgrade


# ------------------------------------------------------------------ music
class ScoreTrackTests(unittest.TestCase):
    def test_genre_and_mood_match_scores_highest(self):
        score, qualifies, reasons = music.score_track(
            {"genre": "ambient", "mood": "mellow", "tempo_bpm": 60},
            {"genre": "ambient", "mood": "mellow", "tempo_bpm_median": 60})
        self.assertTrue(qualifies)
        self.assertEqual(score, 7.0)  # 3 genre + 2 mood + 2 tempo
        self.assertTrue(any("genre" in r for r in reasons))

    def test_no_genre_or_mood_match_does_not_qualify(self):
        _, qualifies, _ = music.score_track(
            {"genre": "pop", "mood": "upbeat", "tempo_bpm": 125},
            {"genre": "ambient", "mood": "mellow", "tempo_bpm_median": 60})
        self.assertFalse(qualifies)

    def test_empty_profile_qualifies_any_track(self):
        _, qualifies, _ = music.score_track(
            {"genre": "pop", "mood": "upbeat", "tempo_bpm": 125}, {})
        self.assertTrue(qualifies)

    def test_tempo_score_fades_with_distance(self):
        close, _, _ = music.score_track(
            {"genre": "ambient", "tempo_bpm": 62}, {"genre": "ambient", "tempo_bpm_median": 60})
        far, _, _ = music.score_track(
            {"genre": "ambient", "tempo_bpm": 105}, {"genre": "ambient", "tempo_bpm_median": 60})
        self.assertGreater(close, far)
        self.assertAlmostEqual(far, 3.0)  # genre only; tempo contributes 0 at diff 45


class LibrarySelectionTests(unittest.TestCase):
    def test_example_tracks_are_skipped(self):
        config = {"music_library": [
            {"file": "music/example-fast-upbeat-pop.mp3", "genre": "pop",
             "tempo_bpm": 125, "mood": "upbeat", "example": True}]}
        self.assertEqual(music.available_library(config), [])
        track, log = music.select_track(config, {})
        self.assertIsNone(track)
        self.assertEqual(log["reason"], "no usable (non-example) music library configured")

    def test_missing_file_skipped_with_warning(self):
        config = {"music_library": [
            {"file": "/tmp/no-such-track-xyz.mp3", "genre": "ambient",
             "tempo_bpm": 60, "mood": "mellow"}]}
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            lib = music.available_library(config)
        self.assertEqual(lib, [])
        self.assertIn("Skipping music library entry with missing file", err.getvalue())

    def test_http_track_accepted_without_downloading(self):
        config = {"music_library": [
            {"url": "https://example.org/bed.mp3", "genre": "ambient",
             "tempo_bpm": 60, "mood": "mellow"}]}
        self.assertEqual(len(music.available_library(config)), 1)

    def test_local_file_accepted_and_best_match_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "good.mp3")
            weak = os.path.join(tmp, "weak.mp3")
            for path in (good, weak):
                with open(path, "wb") as fh:
                    fh.write(b"x" * 100)
            config = {"music_library": [
                {"file": weak, "genre": "ambient", "tempo_bpm": 120, "mood": "tense"},
                {"file": good, "genre": "ambient", "tempo_bpm": 60, "mood": "mellow"}]}
            track, log = music.select_track(
                config, {"genre": "ambient", "mood": "mellow", "tempo_bpm_median": 60})
            self.assertEqual(track["file"], good)
            self.assertEqual(log["score"], 7.0)

    def test_no_match_fails_loudly_naming_wanted_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            track_path = os.path.join(tmp, "pop.mp3")
            with open(track_path, "wb") as fh:
                fh.write(b"x" * 100)
            config = {"music_library": [
                {"file": track_path, "genre": "pop", "tempo_bpm": 125, "mood": "upbeat"}]}
            track, log = music.select_track(
                config, {"genre": "ambient", "mood": "mellow", "tempo_bpm_median": 60})
            self.assertIsNone(track)
            self.assertEqual(log["reason"], "no_match")
            self.assertEqual(log["wanted"]["genre"], "ambient")

    def test_main_returns_1_on_no_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            track_path = os.path.join(tmp, "pop.mp3")
            with open(track_path, "wb") as fh:
                fh.write(b"x" * 100)
            config_path = os.path.join(tmp, "config.yaml")
            with open(config_path, "w", encoding="utf-8") as fh:
                fh.write("music_library:\n"
                         f'  - file: "{track_path}"\n'
                         '    genre: "pop"\n'
                         "    tempo_bpm: 125\n"
                         '    mood: "upbeat"\n'
                         'licensed_track: ""\n')
            narr_path = os.path.join(tmp, "narr.wav")
            write_wav(narr_path, seconds=1.0)
            err = io.StringIO()
            with contextlib.redirect_stderr(err), patch.object(music, "append_run_log"):
                rc = music.main(["--narration", narr_path,
                                 "--output", os.path.join(tmp, "out.mp3"),
                                 "--config", config_path,
                                 "--profile", json.dumps(
                                     {"genre": "ambient", "mood": "mellow",
                                      "tempo_bpm_median": 60})])
            self.assertEqual(rc, 1)
            self.assertIn("No royalty-free track", err.getvalue())
            self.assertIn("ambient", err.getvalue())

    def test_ensure_track_file_returns_local_path_unchanged(self):
        self.assertEqual(music.ensure_track_file({"file": "/tmp/bed.mp3"}), "/tmp/bed.mp3")

    def test_legacy_music_file_local_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            bed = os.path.join(tmp, "bed.mp3")
            with open(bed, "wb") as fh:
                fh.write(b"x" * 100)
            self.assertEqual(music.legacy_music_file({"music_file": bed}, ""), bed)
        self.assertEqual(music.legacy_music_file({"music_file": ""}, ""), "")


class BranchConfigSafeguardsTests(unittest.TestCase):
    def test_branch_config_has_no_licensed_or_legacy_track(self):
        config = load_config(os.path.join(BRANCH_ROOT, "config.yaml"))
        self.assertEqual(config.get("licensed_track"), "")
        self.assertEqual(config.get("license_note"), "")
        self.assertEqual(config.get("music_file"), "")
        self.assertEqual([u for u in config.get("music_urls", []) if u], [])
        library = config.get("music_library") or []
        # One real track: the in-house bed (config.yaml:96-101), plus
        # three EXAMPLE placeholders that the matcher must skip.
        real = [t for t in library if not t.get("example")]
        self.assertEqual(len(real), 1)
        self.assertEqual(real[0]["file"], "music/mellow_history_bed.mp3")
        self.assertEqual(real[0]["genre"], "ambient")
        self.assertEqual(real[0]["tempo_bpm"], 60)
        self.assertEqual(real[0]["mood"], "mellow")
        self.assertIn("royalty-free", real[0]["license"])
        self.assertEqual(len([t for t in library if t.get("example")]), 3)
        # The in-house bed is tracked in this branch and must be available.
        bed_path = os.path.join(BRANCH_ROOT, "music", "mellow_history_bed.mp3")
        self.assertTrue(os.path.isfile(bed_path))
        available = music.available_library(config)
        self.assertEqual(len(available), 1)
        self.assertEqual(available[0]["file"], "music/mellow_history_bed.mp3")

    def test_real_bed_selected_when_present(self):
        # Same bed entry, pointed at a real file: it must win a perfect
        # ambient / 60 BPM / mellow profile match.
        with tempfile.TemporaryDirectory() as tmp:
            bed = os.path.join(tmp, "mellow_history_bed.mp3")
            with open(bed, "wb") as fh:
                fh.write(b"x" * 100)
            config = {"music_library": [
                {"file": bed, "genre": "ambient", "tempo_bpm": 60,
                 "mood": "mellow", "license": "synthesized in-house, royalty-free",
                 "example": False}]}
            track, log = music.select_track(
                config, {"genre": "ambient", "mood": "mellow", "tempo_bpm_median": 60})
            self.assertEqual(track["file"], bed)
            self.assertEqual(log["score"], 7.0)


if __name__ == "__main__":
    unittest.main()
