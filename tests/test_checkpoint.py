"""Tests for Phase 3 item 7: checkpoint/resume (src/checkpoint.py,
wired into src/run.py build_format with --resume).

A checkpoint is trusted only after checksum + input fingerprint +
TTL + per-output sha256 all validate. Stale or corrupt checkpoints
are discarded, never trusted blindly. QA always re-runs, even on a
resumed run.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.checkpoint import (DEFAULT_TTL_SECONDS, compute_fingerprint,
                            file_sha256, load_checkpoint, record_stage,
                            save_checkpoint)

INPUTS = {"format": "short", "niche": "history",
          "scripts_sha256": "abc123", "narrator_voice": "bm_george",
          "music_volume": 0.06, "caption_preset": "documentary"}


def _make_outputs(tmp, names=("a.txt", "b.txt")):
    paths = []
    for name in names:
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"contents of {name}")
        paths.append(path)
    return paths


class FingerprintTests(unittest.TestCase):
    def test_same_inputs_same_fingerprint(self):
        self.assertEqual(compute_fingerprint(INPUTS),
                         compute_fingerprint(dict(INPUTS)))

    def test_any_input_change_changes_fingerprint(self):
        for key in ("format", "niche", "scripts_sha256",
                    "narrator_voice", "music_volume", "caption_preset"):
            changed = dict(INPUTS)
            changed[key] = "CHANGED"
            self.assertNotEqual(compute_fingerprint(INPUTS),
                                compute_fingerprint(changed),
                                f"fingerprint ignored change to {key}")


class SaveLoadTests(unittest.TestCase):
    def test_round_trip_and_mode_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _make_outputs(tmp)
            stages = {}
            record_stage(stages, "narrate", outputs)
            path = os.path.join(tmp, "checkpoint.json")
            save_checkpoint(path, compute_fingerprint(INPUTS), stages)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            loaded, reason = load_checkpoint(
                path, compute_fingerprint(INPUTS))
            self.assertIsNone(reason)
            self.assertEqual(set(loaded), {"narrate"})
            self.assertEqual(loaded["narrate"]["outputs"], outputs)

    def test_missing_file_discarded(self):
        loaded, reason = load_checkpoint("/tmp/does-not-exist-ckpt.json",
                                         compute_fingerprint(INPUTS))
        self.assertIsNone(loaded)
        self.assertIn("no checkpoint", reason)

    def test_corrupt_json_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "checkpoint.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            loaded, reason = load_checkpoint(path, compute_fingerprint(INPUTS))
            self.assertIsNone(loaded)
            self.assertIn("unreadable", reason)

    def test_tampered_checksum_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _make_outputs(tmp)
            stages = {}
            record_stage(stages, "narrate", outputs)
            path = os.path.join(tmp, "checkpoint.json")
            save_checkpoint(path, compute_fingerprint(INPUTS), stages)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            data["stages"]["narrate"]["hashes"][outputs[0]] = "0" * 64
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            loaded, reason = load_checkpoint(path, compute_fingerprint(INPUTS))
            self.assertIsNone(loaded)
            self.assertIn("checksum mismatch", reason)

    def test_fingerprint_mismatch_discards_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _make_outputs(tmp)
            stages = {}
            record_stage(stages, "narrate", outputs)
            path = os.path.join(tmp, "checkpoint.json")
            save_checkpoint(path, compute_fingerprint(INPUTS), stages)
            loaded, reason = load_checkpoint(
                path, compute_fingerprint({**INPUTS, "music_volume": 0.15}))
            self.assertIsNone(loaded)
            self.assertIn("fingerprint mismatch", reason)

    def test_stale_checkpoint_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _make_outputs(tmp)
            stages = {}
            record_stage(stages, "narrate", outputs)
            path = os.path.join(tmp, "checkpoint.json")
            save_checkpoint(path, compute_fingerprint(INPUTS), stages)
            old_now = datetime.now(timezone.utc) + timedelta(
                seconds=DEFAULT_TTL_SECONDS + 60)
            loaded, reason = load_checkpoint(
                path, compute_fingerprint(INPUTS), now=old_now)
            self.assertIsNone(loaded)
            self.assertIn("stale", reason)

    def test_changed_output_drops_only_that_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_a = _make_outputs(tmp, ("a.txt",))
            out_b = _make_outputs(tmp, ("b.txt",))
            stages = {}
            record_stage(stages, "narrate", out_a)
            record_stage(stages, "music", out_b)
            path = os.path.join(tmp, "checkpoint.json")
            save_checkpoint(path, compute_fingerprint(INPUTS), stages)
            # Corrupt the music output after checkpointing.
            with open(out_b[0], "w", encoding="utf-8") as fh:
                fh.write("different bytes now")
            loaded, reason = load_checkpoint(path, compute_fingerprint(INPUTS))
            self.assertEqual(set(loaded), {"narrate"})
            self.assertIn("music", reason)
            self.assertIn("changed", reason)

    def test_missing_output_drops_only_that_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_a = _make_outputs(tmp, ("a.txt",))
            out_b = _make_outputs(tmp, ("b.txt",))
            stages = {}
            record_stage(stages, "narrate", out_a)
            record_stage(stages, "music", out_b)
            path = os.path.join(tmp, "checkpoint.json")
            save_checkpoint(path, compute_fingerprint(INPUTS), stages)
            os.remove(out_b[0])
            loaded, reason = load_checkpoint(path, compute_fingerprint(INPUTS))
            self.assertEqual(set(loaded), {"narrate"})
            self.assertIn("music", reason)
            self.assertIn("missing", reason)

    def test_wrong_schema_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _make_outputs(tmp)
            stages = {}
            record_stage(stages, "narrate", outputs)
            path = os.path.join(tmp, "checkpoint.json")
            save_checkpoint(path, compute_fingerprint(INPUTS), stages)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            data["schema_version"] = 999
            # Re-sign so only the version check trips.
            from src.checkpoint import _canonical
            import hashlib
            data["checksum"] = hashlib.sha256(
                _canonical({k: v for k, v in data.items()
                            if k != "checksum"})).hexdigest()
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            loaded, reason = load_checkpoint(path, compute_fingerprint(INPUTS))
            self.assertIsNone(loaded)
            self.assertIn("schema version", reason)

    def test_record_stage_missing_output_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                record_stage({}, "video", [os.path.join(tmp, "nope.mp4")])


def _write_scripts(path, text="hello world this is a test"):
    scripts = [{"rank": 1, "topic": "Test Topic", "text": text,
                "claim_ids": []}]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(scripts, fh)
    return scripts


class BuildFormatResumeTests(unittest.TestCase):
    """build_format with fake subprocess stages: prove --resume skips
    finished stages, re-runs QA, and discards bad checkpoints."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        os.makedirs("data", exist_ok=True)
        self.scripts_path = os.path.join(self.tmp.name, "scripts.json")
        _write_scripts(self.scripts_path)
        self.config = {"music_volume": 0.06, "narrator_tier": "local",
                       "narrator_voice": "bm_george", "narrator_speed": 0.9}
        self.calls = {"narrate": 0, "music": 0, "transcribe": 0,
                      "video": 0, "qa": 0}

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def _fake_run_cmd(self, cmd, step, log):
        # cmd: [python, -m, src.<module>, ...flags]
        module = cmd[2] if len(cmd) > 2 else ""
        if module == "src.narrate":
            self.calls["narrate"] += 1
            outdir = cmd[cmd.index("--outdir") + 1]
            os.makedirs(outdir, exist_ok=True)
            with open(os.path.join(outdir, "01-test-topic.mp3"), "wb") as fh:
                fh.write(b"fake narration")
        elif module == "src.music":
            self.calls["music"] += 1
            out = cmd[cmd.index("--output") + 1]
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as fh:
                fh.write(b"fake mixed audio")
        elif module == "src.video":
            self.calls["video"] += 1
            outdir = cmd[cmd.index("--outdir") + 1]
            os.makedirs(outdir, exist_ok=True)
            for suffix in (".mp4", ".mp4.ass", ".mp4.visuals.json"):
                with open(os.path.join(outdir, "01-test-topic" + suffix),
                          "wb") as fh:
                    fh.write(b"fake video " + suffix.encode())
        else:
            raise AssertionError(f"unexpected run_cmd module: {cmd}")

    def _fake_transcribe(self, audio_path, timings_path, model="small"):
        self.calls["transcribe"] += 1
        os.makedirs(os.path.dirname(timings_path), exist_ok=True)
        triples = [(0.0, 1.0, "hello"), (1.1, 2.0, "world")]
        with open(timings_path, "w", encoding="utf-8") as fh:
            json.dump(triples, fh)
        return triples

    def _fake_run_qa(self, *args, **kwargs):
        self.calls["qa"] += 1
        return True

    def _run_build(self, resume):
        from src.run import build_format
        args = SimpleNamespace(skip_video=False, resume=resume)
        log = {"started_at": "2026-11-21T00:00:00Z", "steps": []}
        with patch("src.run.run_cmd", side_effect=self._fake_run_cmd), \
                patch("src.run.transcribe_narration",
                      side_effect=self._fake_transcribe), \
                patch("src.run.run_qa", side_effect=self._fake_run_qa):
            outputs, _ = build_format(log, "short", self.scripts_path,
                                      self.config, "history", args)
        return outputs, log

    def test_fresh_run_runs_everything_and_checkpoints(self):
        outputs, _ = self._run_build(resume=False)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.calls,
                         {"narrate": 1, "music": 1, "transcribe": 1,
                          "video": 1, "qa": 1})
        ckpt = os.path.join(self.tmp.name, "data", "checkpoint_short.json")
        self.assertTrue(os.path.exists(ckpt))
        self.assertEqual(stat.S_IMODE(os.stat(ckpt).st_mode), 0o600)
        with open(ckpt, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(set(data["stages"]),
                         {"narrate", "music", "transcribe", "video"})

    def test_resume_skips_finished_stages_but_reruns_qa(self):
        self._run_build(resume=False)
        self.calls = {k: 0 for k in self.calls}
        outputs, log = self._run_build(resume=True)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.calls["narrate"], 0)
        self.assertEqual(self.calls["music"], 0)
        self.assertEqual(self.calls["transcribe"], 0)
        self.assertEqual(self.calls["video"], 0)
        # QA is never checkpointed: it re-runs on the reused video.
        self.assertEqual(self.calls["qa"], 1)
        self.assertTrue(any(s["step"] == "checkpoint:short"
                            and s["status"] == "ok"
                            for s in log["steps"]))

    def test_resume_after_deleted_video_rerenders_only_video(self):
        self._run_build(resume=False)
        os.remove(os.path.join(self.tmp.name, "data", "videos_short",
                               "01-test-topic.mp4"))
        self.calls = {k: 0 for k in self.calls}
        outputs, _ = self._run_build(resume=True)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.calls["narrate"], 0)
        self.assertEqual(self.calls["music"], 0)
        self.assertEqual(self.calls["transcribe"], 0)
        self.assertEqual(self.calls["video"], 1)
        self.assertEqual(self.calls["qa"], 1)

    def test_resume_after_script_change_reruns_everything(self):
        self._run_build(resume=False)
        _write_scripts(self.scripts_path, text="a completely different script")
        self.calls = {k: 0 for k in self.calls}
        outputs, log = self._run_build(resume=True)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.calls["narrate"], 1)
        self.assertEqual(self.calls["music"], 1)
        self.assertEqual(self.calls["transcribe"], 1)
        self.assertEqual(self.calls["video"], 1)
        self.assertEqual(self.calls["qa"], 1)
        self.assertTrue(any(s["step"] == "checkpoint:short"
                            and "fingerprint mismatch" in s["detail"]
                            for s in log["steps"]))

    def test_resume_with_tampered_checkpoint_reruns_everything(self):
        self._run_build(resume=False)
        ckpt = os.path.join(self.tmp.name, "data", "checkpoint_short.json")
        with open(ckpt, encoding="utf-8") as fh:
            data = json.load(fh)
        data["stages"]["video"]["hashes"] = {}
        with open(ckpt, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        self.calls = {k: 0 for k in self.calls}
        outputs, _ = self._run_build(resume=True)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.calls["video"], 1)


if __name__ == "__main__":
    unittest.main()
