"""Pipeline-hardening tests for the 7 production-readiness issues
(docs/production-readiness-2026-11-12.md §5), fixed 2026-11-15.

Fixture-based, no network. The real-mix test needs ffmpeg/ffprobe
(and numpy) and skips cleanly without them; the mix-command test
covers the same fix without ffmpeg.
"""
import json
import math
import os
import shutil
import stat
import struct
import sys
import tempfile
import unittest
import wave
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import music, narrate, review, run as run_mod, upload, visuals
from src.visual_qa import check_visual_manifest

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:  # pragma: no cover
    HAS_NUMPY = False

BRANCH_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write_wav(path, fn, seconds, sr=24000):
    frames = int(seconds * sr)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes(b"".join(
            struct.pack("<h", int(max(-1, min(1, fn(i / sr))) * 32767))
            for i in range(frames)))


class _ChdirTemp:
    """Context manager: run a test inside a fresh temp cwd."""

    def __init__(self, test):
        self.test = test

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.test.addCleanup(self.tmp.cleanup)
        self.saved = os.getcwd()
        os.chdir(self.tmp.name)
        return self.tmp.name

    def __exit__(self, *exc):
        os.chdir(self.saved)
        return False


# ---------------------------------------------------------------- issue 1
class ReviewNoConfigWriteTests(unittest.TestCase):
    def _stats(self, tmp):
        now = datetime.now(timezone.utc).isoformat()
        videos = []
        for i, views in enumerate((500, 300, 100)):
            videos.append({
                "video_id": f"v{i}", "title": f"Video {i}",
                "niche": "history mysteries", "hook_style": "question",
                "length_seconds": 45, "music_genre": "ambient",
                "music_tempo_bpm": 60, "music_mood": "mellow",
                "publish_time": now, "published_date": now,
                "views": views, "avg_view_duration_seconds": 30,
                "retention_pct": 50, "likes": 10, "comments": 2})
        path = os.path.join(tmp, "stats.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(videos, fh)
        return path

    def test_apply_adjustments_computes_without_touching_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = os.path.join(tmp, "config.yaml")
            with open(config, "w", encoding="utf-8") as fh:
                fh.write('niche: "history mysteries investigated with modern tech"\n')
            before_bytes = _read_bytes(config)
            shared = {"niche": "history mysteries", "hook_style": "question",
                      "length_seconds": 45, "music_genre": "ambient",
                      "music_tempo_bpm": 60, "music_mood": "mellow",
                      "publish_hours": ["19", "19", "18"]}
            before, after, applied = review.apply_adjustments(
                config, shared, [{"title": "top"}])
            self.assertEqual(_read_bytes(config), before_bytes,
                             "apply_adjustments must not write config.yaml")
            self.assertEqual(after["review_preferred_hook_style"], "question")
            self.assertEqual(after["review_preferred_length_seconds"], 45)
            self.assertTrue(applied, "computed adjustments must be reported")

    def test_main_writes_adjustments_to_data_files_only(self):
        with _ChdirTemp(self) as tmp:
            config = os.path.join(tmp, "config.yaml")
            with open(config, "w", encoding="utf-8") as fh:
                fh.write('niche: "history mysteries investigated with modern tech"\n')
            before_bytes = _read_bytes(config)
            stats = self._stats(tmp)
            out = os.path.join(tmp, "weekly_review.md")
            jout = os.path.join(tmp, "weekly_review.json")
            hist = os.path.join(tmp, "review_history.json")
            adj = os.path.join(tmp, "review_adjustments.json")
            rc = review.main(["--stats", stats, "--config", config,
                              "--output", out, "--json-output", jout,
                              "--history", hist, "--adjustments", adj])
            self.assertEqual(rc, 0)
            self.assertEqual(_read_bytes(config), before_bytes,
                             "review.main must not write config.yaml")
            with open(adj, encoding="utf-8") as fh:
                adjustments = json.load(fh)
            self.assertTrue(adjustments["adjustments"])
            self.assertIn("NOT modified", adjustments["note"])
            self.assertEqual(adjustments["after"]["review_preferred_hook_style"],
                             "question")
            with open(jout, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertTrue(report["adjustments_applied"])
            self.assertIn("NOT written to config.yaml",
                          _read_text(out))


# ------------------------------------------------------------- issues 2 & 3
class UploadPlanAndTokenTests(unittest.TestCase):
    def test_plan_rejects_publish_at_loudly(self):
        with self.assertRaisesRegex(ValueError, "Scheduled publishing is disabled"):
            upload.plan("v.mp4", "T", "D", "unlisted",
                        publish_at="2026-11-13T12:00:00Z")

    def test_plan_without_publish_at_is_unchanged(self):
        plan = upload.plan("v.mp4", "T", "D", "unlisted")
        self.assertEqual(plan["privacyStatus"], "unlisted")
        self.assertNotIn("publishAt", plan)

    def test_upload_source_has_no_scheduled_publish_branch(self):
        path = os.path.join(BRANCH_ROOT, "src", "upload.py")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("publishAt", text)
        self.assertNotIn('status["publishAt"]', text)

    def test_save_token_sets_mode_600(self):
        class FakeCreds:
            def to_json(self):
                return '{"token": "fake"}'

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token.json")
            upload._save_token(FakeCreds(), path)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), {"token": "fake"})


# ---------------------------------------------------------------- issue 4
class MusicMixTests(unittest.TestCase):
    def test_mix_command_keeps_levels_and_loops_bed(self):
        cmd = music.mix_command("narr.mp3", "bed.mp3", "out.mp3", 0.06)
        self.assertIn("-stream_loop", cmd)
        self.assertIn("-1", cmd)
        filt = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("normalize=0", filt,
                      "amix must not halve both inputs (~6 dB drop)")
        self.assertIn("duration=first", filt)
        self.assertIn("volume=0.06", filt)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe")
                         and HAS_NUMPY, "needs ffmpeg/ffprobe + numpy")
    def test_real_mix_bed_level_and_looping(self):
        # Narration: 1s tone then 2s silence (3s total). Bed: 1s tone,
        # shorter than the narration, so the 2-3s gap proves looping.
        with _ChdirTemp(self) as tmp:
            os.makedirs("data", exist_ok=True)
            _write_wav(os.path.join(tmp, "narr.wav"),
                       lambda t: 0.5 * math.sin(2 * math.pi * 440 * t) if t < 1 else 0.0,
                       3.0)
            _write_wav(os.path.join(tmp, "bed.wav"),
                       lambda t: 0.5 * math.sin(2 * math.pi * 880 * t), 1.0)
            config = os.path.join(tmp, "config.yaml")
            with open(config, "w", encoding="utf-8") as fh:
                fh.write('music_library:\n  - file: "bed.wav"\n'
                         '    genre: "ambient"\n    tempo_bpm: 60\n'
                         '    mood: "mellow"\nlicensed_track: ""\n')
            out = os.path.join(tmp, "out.mp3")
            with patch.object(music, "append_run_log"):
                rc = music.main(["--narration", os.path.join(tmp, "narr.wav"),
                                 "--music", os.path.join(tmp, "bed.wav"),
                                 "--output", out, "--config", config,
                                 "--music-volume", "0.06",
                                 "--top5", "data/top5.json"])
            self.assertEqual(rc, 0)
            import subprocess
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", out,
                            os.path.join(tmp, "out.wav")], check=True)
            with wave.open(os.path.join(tmp, "out.wav")) as fh:
                sr = fh.getframerate()
                x = np.frombuffer(fh.readframes(fh.getnframes()),
                                  dtype=np.int16).astype(float) / 32768.0

            def rms(a, b):
                seg = x[int(a * sr):int(b * sr)]
                return float(np.sqrt(np.mean(seg ** 2)))

            # Narration at full level: sine amp 0.5 -> RMS ~0.354.
            # The old amix default (normalize=1) halved it to ~0.177.
            self.assertGreater(rms(0.1, 0.9), 0.25)
            # Bed at the configured 0.06 in a narration-silent gap:
            # sine amp 0.5 * 0.06 -> RMS ~0.0212.
            self.assertAlmostEqual(rms(1.2, 1.9), 0.0212, delta=0.009)
            # Same gap past the 1s bed length: bed must still be there
            # (looped), not silence.
            self.assertAlmostEqual(rms(2.2, 2.9), 0.0212, delta=0.009)


# ---------------------------------------------------------------- issue 5
class NarrationSpeedValidationTests(unittest.TestCase):
    def test_validate_speed_accepts_bounds(self):
        for speed in (0.5, 0.9, 1.0, 2.0, "1.5"):
            self.assertEqual(narrate.validate_speed(speed), float(speed))

    def test_validate_speed_rejects_out_of_range(self):
        for speed in (0.49, 2.01, 0, -1, 10):
            with self.subTest(speed=speed):
                with self.assertRaisesRegex(ValueError, "between 0.5 and 2.0"):
                    narrate.validate_speed(speed)

    def test_validate_speed_rejects_non_numeric(self):
        for speed in ("fast", None, float("nan"), float("inf")):
            with self.subTest(speed=speed):
                with self.assertRaises(ValueError):
                    narrate.validate_speed(speed)

    def test_humanize_text_rejects_bad_speed(self):
        with self.assertRaises(ValueError):
            narrate.humanize_text("Hello world.", speed=3.0)

    def test_main_rejects_bad_speed_in_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = os.path.join(tmp, "scripts.json")
            with open(scripts, "w", encoding="utf-8") as fh:
                json.dump([{"rank": 1, "topic": "Test",
                            "text": "Hello world. This is a test."}], fh)
            config = os.path.join(tmp, "config.yaml")
            with open(config, "w", encoding="utf-8") as fh:
                fh.write('narrator_voice: "bm_george"\n'
                         'narrator_tier: "free"\n'
                         'narrator_speed: 3.0\n')
            rc = narrate.main(["--input", scripts,
                               "--outdir", os.path.join(tmp, "audio"),
                               "--config", config])
            self.assertEqual(rc, 1)

    def test_main_rejects_bad_speed_on_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = os.path.join(tmp, "scripts.json")
            with open(scripts, "w", encoding="utf-8") as fh:
                json.dump([{"rank": 1, "topic": "Test",
                            "text": "Hello world. This is a test."}], fh)
            config = os.path.join(tmp, "config.yaml")
            with open(config, "w", encoding="utf-8") as fh:
                fh.write('narrator_voice: "bm_george"\n'
                         'narrator_tier: "free"\n'
                         'narrator_speed: 0.9\n')
            rc = narrate.main(["--input", scripts, "--speed", "0.1",
                               "--outdir", os.path.join(tmp, "audio"),
                               "--config", config])
            self.assertEqual(rc, 1)


# ---------------------------------------------------------------- issue 6
class VisualFingerprintTests(unittest.TestCase):
    def test_fingerprint_includes_claim_and_source_ids(self):
        base = visuals.scene_fingerprint("prompt", "wf", "image", ["c1"], ["s1"])
        self.assertNotEqual(
            base, visuals.scene_fingerprint("prompt", "wf", "image", ["c2"], ["s1"]),
            "changing claim_ids must change the fingerprint")
        self.assertNotEqual(
            base, visuals.scene_fingerprint("prompt", "wf", "image", ["c1"], ["s2"]),
            "changing source_ids must change the fingerprint")
        self.assertEqual(
            base, visuals.scene_fingerprint("prompt", "wf", "image", ["c1"], ["s1"]))
        # ID order must not matter: same evidence, same fingerprint.
        self.assertEqual(
            visuals.scene_fingerprint("p", "w", "image", ["c1", "c2"], ["s1", "s2"]),
            visuals.scene_fingerprint("p", "w", "image", ["c2", "c1"], ["s2", "s1"]))

    def test_claim_change_regenerates_instead_of_reusing_cache(self):
        scene = {"scene": 1, "image_prompt": "same prompt",
                 "claim_ids": ["c1"], "source_ids": ["s1"]}
        calls = []

        def fake_generate(scene_arg, workflow, base_url, outdir, **kwargs):
            calls.append((scene_arg.get("claim_ids"), scene_arg.get("source_ids")))
            path = os.path.join(outdir, "scene-001-image.png")
            with open(path, "wb") as fh:
                fh.write(b"\x89PNG" + b"\x00" * 10)
            return {"path": path, "type": "image", "scene": 1,
                    "claim_ids": list(scene_arg.get("claim_ids", [])),
                    "source_ids": list(scene_arg.get("source_ids", [])),
                    "prompt_id": "p1", "seed": 1,
                    "visual_type": "AI reconstruction: interpretive",
                    "prompt": scene_arg["image_prompt"]}

        workflow = os.path.join(BRANCH_ROOT, "tests", "fixtures",
                                "comfyui_workflow_api.json")
        with tempfile.TemporaryDirectory() as tmp:
            script = {"topic": "T", "format": "short", "scenes": [dict(scene)]}
            with patch.object(visuals, "generate_scene", side_effect=fake_generate):
                visuals.generate_script_assets(script, workflow, "http://x", tmp)
                self.assertEqual(len(calls), 1)
                # Same prompt, different claims: must regenerate, not
                # reuse the cached asset for the wrong claims.
                script["scenes"][0]["claim_ids"] = ["c2"]
                result = visuals.generate_script_assets(
                    script, workflow, "http://x", tmp)
            self.assertEqual(len(calls), 2)
            self.assertEqual(result["assets"][0]["claim_ids"], ["c2"])

    def test_visual_qa_still_catches_claim_mismatch(self):
        script = {"scenes": [{"scene": 1, "claim_ids": ["c1"],
                              "source_ids": ["s1"]}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.png")
            with open(path, "wb") as fh:
                fh.write(b"x" * 10)
            manifest = {"assets": [{"scene": 1, "path": path,
                                    "claim_ids": ["not-a-claim"],
                                    "source_ids": ["s1"],
                                    "visual_type": "AI reconstruction",
                                    "prompt": "p"}],
                        "disclaimer": "AI reconstruction"}
            report = check_visual_manifest(script, manifest)
            self.assertFalse(report["passed"])
            self.assertTrue(any("claim" in e for e in report["errors"]))


# ---------------------------------------------------------------- issue 7
class RunDocumentaryWiringTests(unittest.TestCase):
    def test_script_command_history_niche_uses_documentary_style(self):
        cmd = run_mod.script_command("long", "data/top5_long.json",
                                     "data/scripts_long.json", 1,
                                     "history mysteries investigated with modern tech")
        self.assertEqual(cmd[:3], [sys.executable, "-m", "src.script"])
        self.assertIn("--style", cmd)
        self.assertEqual(cmd[cmd.index("--style") + 1], "history_mystery")
        self.assertIn("--ledger", cmd)
        self.assertEqual(cmd[cmd.index("--ledger") + 1],
                         "data/evidence_ledger.json")

    def test_script_command_short_also_wired(self):
        cmd = run_mod.script_command("short", "data/top5_shorts.json",
                                     "data/scripts_shorts.json", 2,
                                     "history mysteries investigated with modern tech")
        self.assertIn("history_mystery", cmd)
        self.assertIn("short", cmd)

    def test_script_command_other_niche_omits_style(self):
        # Deliberate minimal scope: for a non-history niche run.py
        # leaves src.script.py's previous auto-detection alone (see
        # script_command docstring). This test pins that behaviour.
        cmd = run_mod.script_command("long", "data/top5_long.json",
                                     "data/scripts_long.json", 1,
                                     "personal finance")
        self.assertNotIn("--style", cmd)

    def test_is_history_mystery_niche(self):
        self.assertTrue(run_mod.is_history_mystery_niche(
            "history mysteries investigated with modern tech"))
        self.assertTrue(run_mod.is_history_mystery_niche("History Mysteries"))
        self.assertFalse(run_mod.is_history_mystery_niche("personal finance"))
        self.assertFalse(run_mod.is_history_mystery_niche(""))

    def test_run_script_command_produces_documentary_package(self):
        # The exact command run.py now emits for a history-mystery
        # run must produce an evidence-led documentary package, not
        # a generic template script.
        from src import script as script_mod

        with _ChdirTemp(self) as tmp:
            config = os.path.join(tmp, "config.yaml")
            with open(config, "w", encoding="utf-8") as fh:
                fh.write('niche: "history mysteries investigated with modern tech"\n'
                         'niches:\n'
                         '  - history mysteries investigated with modern tech\n')
            source = {"source_id": "s1", "title": "Museum catalogue",
                      "url": "https://museum.example.org/catalogue",
                      "review_status": "APPROVED",
                      "publication": "Museum collection catalogue",
                      "publication_year": 2020, "notes": "Reviewed record"}
            ledger = {"schema_version": 1, "sources": [source], "claims": [{
                "claim_id": "c1", "topic": "Test topic",
                "text": "A verified historical statement. " * 25,
                "status": "KNOWN", "source_ids": ["s1"],
                "reviewed_by": "editor",
                "reviewed_at": "2026-11-09T00:00:00Z", "shock_hook": True}]}
            ledger_path = os.path.join(tmp, "ledger.json")
            with open(ledger_path, "w", encoding="utf-8") as fh:
                json.dump(ledger, fh)
            cands = os.path.join(tmp, "top5.json")
            with open(cands, "w", encoding="utf-8") as fh:
                json.dump([{"topic": "Test topic"}], fh)
            out = os.path.join(tmp, "scripts.json")
            cmd = run_mod.script_command(
                "short", cands, out, 1,
                "history mysteries investigated with modern tech")
            # cmd is [python, -m, src.script, ...]: run the same
            # arguments through script.main, with the temp ledger/config.
            argv = [a for a in cmd[3:]
                    if a not in ("--ledger", "data/evidence_ledger.json")]
            argv += ["--ledger", ledger_path, "--config", config]
            rc = script_mod.main(argv)
            self.assertEqual(rc, 0)
            with open(out, encoding="utf-8") as fh:
                scripts = json.load(fh)
            self.assertEqual(len(scripts), 1)
            package = scripts[0]
            self.assertEqual(package["style"], "history_mystery")
            self.assertEqual(package["claim_ids"], ["c1"])
            self.assertEqual(package["scenes"][0]["claim_ids"], ["c1"])
            self.assertIn("A verified historical statement.",
                          package["text"])


if __name__ == "__main__":
    unittest.main()
