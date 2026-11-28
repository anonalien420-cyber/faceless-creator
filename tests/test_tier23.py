"""Tests for Tier 2 (reach + learning) and Tier 3 (quality + operations).

Pure-Python tests run everywhere; render checks are gated on ffmpeg +
ffprobe (same convention as the other test modules). Covers: semantic
topic dedupe, multi-language voice/metadata, learned publish hour,
doctor readiness, ops backup/restore/quota, engagement drafts, the
speech-rate QA gate, config validation, upload language wiring, and the
Shorts loop-ending / cover-frame render steps.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import config, doctor, engage, localize, ops, qa, scheduler, similarity, upload

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
requires_ffmpeg = unittest.skipUnless(HAS_FFMPEG, "ffmpeg + ffprobe required")


class _TmpCwd(unittest.TestCase):
    """Run each test in its own cwd so data/ writes never leak."""

    def setUp(self):
        self._old = os.getcwd()
        self._tmp = tempfile.mkdtemp()
        os.chdir(self._tmp)
        os.makedirs("data", exist_ok=True)

    def tearDown(self):
        os.chdir(self._old)
        shutil.rmtree(self._tmp, ignore_errors=True)


# ------------------------------------------------------- semantic dedupe
class SimilarityTests(unittest.TestCase):
    def test_exact_match_is_similar(self):
        dup, matched, score = similarity.is_similar_topic(
            "The lost city of Atlantis", ["The lost city of Atlantis"], 0.6)
        self.assertTrue(dup)
        self.assertEqual(matched, "The lost city of Atlantis")
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_paraphrase_is_similar(self):
        dup, matched, score = similarity.is_similar_topic(
            "Atlantis forgotten ruins lost city",
            ["The lost city of Atlantis", "The Voynich manuscript decoded"], 0.6)
        self.assertTrue(dup)
        self.assertEqual(matched, "The lost city of Atlantis")
        self.assertGreaterEqual(score, 0.6)

    def test_distinct_entity_not_merged(self):
        # "lost city of Petra" shares framing but is a DIFFERENT story —
        # the guard must not silently drop it (precision over recall).
        dup, _, _ = similarity.is_similar_topic(
            "The lost city of Petra",
            ["The lost city of Atlantis", "The Voynich manuscript decoded",
             "The dancing plague of 1518"], 0.6)
        self.assertFalse(dup)

    def test_unrelated_topic(self):
        dup, matched, score = similarity.is_similar_topic(
            "A completely unrelated cooking recipe",
            ["The lost city of Atlantis"], 0.6)
        self.assertFalse(dup)
        self.assertEqual(score, 0.0)

    def test_empty_history(self):
        self.assertEqual(similarity.is_similar_topic("anything", [], 0.6), (False, "", 0.0))

    def test_threshold_one_is_exact_only(self):
        dup, _, _ = similarity.is_similar_topic(
            "Atlantis forgotten ruins lost city", ["The lost city of Atlantis"], 1.0)
        self.assertFalse(dup)

    def test_tokenize_drops_stopwords_and_stems(self):
        tokens = similarity.tokenize("The lost cities of Rome")
        self.assertNotIn("the", tokens)
        self.assertNotIn("of", tokens)
        self.assertIn("rome", tokens)
        self.assertIn("city", tokens)  # cities -> city

    def test_stemming_is_consistent_both_sides(self):
        # The crude stemmer may mangle a proper noun ("atlantis"->"atlanti"),
        # but it does so identically on both sides, so matching still works.
        a = similarity.tokenize("Atlantis")
        b = similarity.tokenize("the Atlantis ruins")
        self.assertEqual(a[0], b[0])

    def test_similarity_bounds(self):
        s = similarity.similarity("ancient roman concrete", "roman concrete secret")
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 1.0)


# ------------------------------------------------------- multi-language
class LocalizeTests(unittest.TestCase):
    def test_voice_for_language_maps(self):
        self.assertEqual(localize.voice_for_language("es-MX", ""), "es-MX-JorgeNeural")
        self.assertEqual(localize.voice_for_language("ja", ""), "ja-JP-KeitaNeural")

    def test_matching_configured_voice_is_kept(self):
        self.assertEqual(localize.voice_for_language("es", "es-ES-AlvaroNeural"),
                         "es-ES-AlvaroNeural")

    def test_mismatched_voice_is_replaced(self):
        self.assertEqual(localize.voice_for_language("fr", "en-US-GuyNeural"),
                         "fr-FR-HenriNeural")

    def test_unknown_language_keeps_current(self):
        self.assertEqual(localize.voice_for_language("xx", "en-US-GuyNeural"),
                         "en-US-GuyNeural")

    def test_english_default(self):
        self.assertEqual(localize.voice_for_language("en", ""), "en-US-ChristopherNeural")

    def test_translate_template_returns_none(self):
        self.assertIsNone(localize.translate_metadata("T", "D", "es", tier="template"))

    def test_translate_english_returns_none(self):
        self.assertIsNone(localize.translate_metadata("T", "D", "en", tier="api"))

    def test_translate_api_without_key_returns_none(self):
        old = {k: os.environ.pop(k, None) for k in ("LLM_API_KEY", "OPENAI_API_KEY")}
        try:
            self.assertIsNone(localize.translate_metadata("T", "D", "es", tier="api"))
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


# ------------------------------------------------------- learned publish hour
class PublishLearningTests(_TmpCwd):
    def _write_hours(self, hour, samples):
        with open("data/publish_hours.json", "w", encoding="utf-8") as fh:
            json.dump({"history mysteries": {"hour": hour, "samples": samples,
                                             "total_views": 50000}}, fh)

    def test_learned_hour_inside_window_is_used(self):
        self._write_hours(18, 7)
        tz = ZoneInfo("America/Chicago")
        now = datetime(2026, 11, 27, 10, 0, tzinfo=tz)  # Friday
        cfg = {"channel_timezone": "America/Chicago", "publish_learning": True}
        start, end = scheduler.next_peak_window("history mysteries", cfg, now=now)
        self.assertEqual(start.hour, 18)
        self.assertEqual(end.hour, 20)

    def test_learning_disabled_uses_window_start(self):
        self._write_hours(18, 7)
        tz = ZoneInfo("America/Chicago")
        now = datetime(2026, 11, 27, 10, 0, tzinfo=tz)
        cfg = {"channel_timezone": "America/Chicago", "publish_learning": False}
        start, _ = scheduler.next_peak_window("history mysteries", cfg, now=now)
        self.assertEqual(start.hour, 17)

    def test_learned_hour_outside_window_is_ignored(self):
        self._write_hours(3, 9)  # 03:00 is outside the 17-20 window
        tz = ZoneInfo("America/Chicago")
        now = datetime(2026, 11, 27, 10, 0, tzinfo=tz)
        cfg = {"channel_timezone": "America/Chicago", "publish_learning": True}
        start, _ = scheduler.next_peak_window("history mysteries", cfg, now=now)
        self.assertEqual(start.hour, 17)  # never invents a 03:00 window

    def test_min_samples_gate(self):
        self._write_hours(18, 2)  # below default min_samples=5
        tz = ZoneInfo("America/Chicago")
        now = datetime(2026, 11, 27, 10, 0, tzinfo=tz)
        cfg = {"channel_timezone": "America/Chicago", "publish_learning": True}
        start, _ = scheduler.next_peak_window("history mysteries", cfg, now=now)
        self.assertEqual(start.hour, 17)

    def test_learned_hour_for_missing_file(self):
        self.assertIsNone(scheduler.learned_hour_for("history mysteries"))

    def test_learned_hour_for_invalid_hour(self):
        with open("data/publish_hours.json", "w", encoding="utf-8") as fh:
            json.dump({"history mysteries": {"hour": 99, "samples": 9}}, fh)
        self.assertIsNone(scheduler.learned_hour_for("history mysteries"))

    def test_review_learn_publish_hours_weighted(self):
        from src.review import learn_publish_hours
        tz = "America/Chicago"
        videos = []
        # 5 videos at 18:00 local with high views, 1 at 12:00 with low views
        for i in range(5):
            videos.append({"niche": "history mysteries", "views": 10000,
                           "publish_time": f"2026-11-{20 + i}T18:00:00-06:00"})
        videos.append({"niche": "history mysteries", "views": 100,
                       "publish_time": "2026-11-26T12:00:00-06:00"})
        learned = learn_publish_hours(videos, tz_name=tz, min_samples=5)
        self.assertEqual(learned["history mysteries"]["hour"], 18)
        self.assertEqual(learned["history mysteries"]["samples"], 6)

    def test_review_learn_requires_min_samples(self):
        from src.review import learn_publish_hours
        videos = [{"niche": "history mysteries", "views": 10000,
                   "publish_time": "2026-11-20T18:00:00-06:00"}]
        self.assertEqual(learn_publish_hours(videos, min_samples=5), {})


# ------------------------------------------------------- doctor
class DoctorTests(_TmpCwd):
    def test_run_checks_structure(self):
        checks = doctor.run_checks("config.yaml")
        self.assertTrue(checks)
        for c in checks:
            self.assertIn(c["status"], ("pass", "warn", "fail"))
            self.assertIn("check", c)
            self.assertIn("detail", c)

    def test_required_tools_present(self):
        checks = {c["check"]: c for c in doctor.run_checks("config.yaml")}
        if HAS_FFMPEG:
            self.assertEqual(checks["ffmpeg"]["status"], "pass")
            self.assertEqual(checks["ffprobe"]["status"], "pass")

    def test_optional_modules_are_warn_not_fail(self):
        checks = doctor.run_checks("config.yaml")
        for c in checks:
            if c["check"].startswith("module:") or c["check"].startswith("key:"):
                self.assertIn(c["status"], ("pass", "warn"))

    def test_data_writable(self):
        checks = {c["check"]: c for c in doctor.run_checks("config.yaml")}
        self.assertEqual(checks["data_writable"]["status"], "pass")

    def test_invalid_config_fails(self):
        with open("bad.yaml", "w", encoding="utf-8") as fh:
            fh.write("narrator_speed: not-a-number\n")
        checks = {c["check"]: c for c in doctor.run_checks("bad.yaml")}
        self.assertEqual(checks["config"]["status"], "fail")


# ------------------------------------------------------- ops backup/quota
class OpsTests(_TmpCwd):
    def _seed(self):
        with open("data/niche_lock.json", "w", encoding="utf-8") as fh:
            json.dump({"niche": "history"}, fh)
        with open("data/topic_history.json", "w", encoding="utf-8") as fh:
            json.dump([{"topic": "X", "date": "2026-11-27"}], fh)

    def test_backup_restore_roundtrip(self):
        self._seed()
        archive = ops.backup_state()
        self.assertTrue(os.path.exists(archive))
        os.remove("data/niche_lock.json")
        restored = ops.restore_state(archive)
        self.assertIn("data/niche_lock.json", restored)
        self.assertTrue(os.path.exists("data/niche_lock.json"))

    def test_restore_ignores_non_allowlisted(self):
        import io
        import tarfile
        archive = "evil.tar.gz"
        escape = f"escape_proof_{os.getpid()}.txt"
        with tarfile.open(archive, "w:gz") as tar:
            # A path-traversal member and a non-allowlisted member must both
            # be skipped; only the known state file is extracted.
            info = tarfile.TarInfo("../" + escape)
            info.size = 5
            tar.addfile(info, io.BytesIO(b"pwned"))
            info2 = tarfile.TarInfo("data/niche_lock.json")
            payload = b'{"niche": "ok"}'
            info2.size = len(payload)
            tar.addfile(info2, io.BytesIO(payload))
        restored = ops.restore_state(archive)
        self.assertEqual(restored, ["data/niche_lock.json"])
        # The traversal target must NOT have been written next to the cwd.
        self.assertFalse(os.path.exists(os.path.join("..", escape)))
        self.assertFalse(os.path.exists(escape))

    def test_same_second_backups_do_not_collide(self):
        self._seed()
        paths = [ops.backup_state() for _ in range(4)]
        self.assertEqual(len(set(paths)), 4)
        self.assertTrue(all(os.path.exists(p) for p in paths))

    def test_prune_keeps_newest(self):
        self._seed()
        for _ in range(5):
            ops.backup_state()
        removed = ops.prune_backups(keep=2)
        remaining = [n for n in os.listdir("data/backups") if n.endswith(".tar.gz")]
        self.assertEqual(len(removed), 3)
        self.assertEqual(len(remaining), 2)

    def test_quota_tracking_and_reset(self):
        self.assertEqual(ops.quota_status("youtube")["used"], 0)
        ops.track_api_call("youtube", 1600)
        ops.track_api_call("youtube", 1600)
        status = ops.quota_status("youtube")
        self.assertEqual(status["used"], 3200)
        self.assertEqual(status["remaining"], 9000 - 3200)
        self.assertFalse(status["warn"])

    def test_quota_warn_at_80_percent(self):
        ops.track_api_call("pexels", 8)
        self.assertTrue(ops.quota_status("pexels", budget=10)["warn"])
        ops.track_api_call("pexels", 1)
        self.assertEqual(ops.quota_status("pexels", budget=10)["remaining"], 1)

    def test_quota_daily_reset(self):
        ops.track_api_call("youtube", 1600)
        # Simulate a stale (yesterday) usage file.
        with open(ops.USAGE_PATH, encoding="utf-8") as fh:
            usage = json.load(fh)
        usage["date"] = "2000-01-01"
        with open(ops.USAGE_PATH, "w", encoding="utf-8") as fh:
            json.dump(usage, fh)
        self.assertEqual(ops.quota_status("youtube")["used"], 0)
        ops.track_api_call("youtube", 1600)
        self.assertEqual(ops.quota_status("youtube")["used"], 1600)


# ------------------------------------------------------- engagement drafts
class EngageTests(_TmpCwd):
    def _script(self):
        return {"topic": "The lost city of Atlantis",
                "hook": "A city vanished overnight.",
                "cta": "What do you think happened?",
                "sources": [{"title": "Wikipedia: Atlantis",
                             "url": "https://en.wikipedia.org/wiki/Atlantis"}]}

    def test_end_screen_long_window(self):
        plan = engage.end_screen_plan(600, fmt="long")
        self.assertEqual(plan["window_start"], 580.0)
        self.assertEqual(plan["window_end"], 600.0)
        self.assertEqual(len(plan["elements"]), 2)

    def test_end_screen_short_is_none(self):
        self.assertIsNone(engage.end_screen_plan(55, fmt="short"))

    def test_end_screen_too_short_is_none(self):
        self.assertIsNone(engage.end_screen_plan(10, fmt="long"))

    def test_community_draft_uses_video_id(self):
        draft = engage.community_draft(self._script(), video_id="abc123")
        self.assertIn("youtu.be/abc123", draft["text"])
        self.assertIn("draft", draft["status"])

    def test_pinned_comment_includes_sources(self):
        draft = engage.pinned_comment_draft(self._script())
        self.assertIn("wikipedia.org", draft["text"])
        self.assertIn("What do you think happened?", draft["text"])

    def test_pinned_comment_no_sources(self):
        draft = engage.pinned_comment_draft({"cta": "Why?"})
        self.assertEqual(draft["text"], "Why?")

    def test_build_drafts_merges_feedback(self):
        bundles = engage.build_drafts(
            [{"script": self._script(), "format": "long", "duration": 600}],
            feedback=[{"topic": "The lost city of Atlantis", "video_id": "vid9"}])
        self.assertEqual(bundles[0]["video_id"], "vid9")

    def test_write_drafts_json_and_md(self):
        path = engage.write_drafts(
            [{"script": self._script(), "format": "long", "duration": 600}])
        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.exists("data/engagement_drafts.md"))
        payload = json.load(open(path, encoding="utf-8"))
        self.assertIn("DRAFTS ONLY", payload["note"])
        self.assertEqual(len(payload["drafts"]), 1)


# ------------------------------------------------------- speech-rate QA gate
class SpeechRateTests(unittest.TestCase):
    def test_no_narration_returns_none(self):
        self.assertIsNone(qa._speech_rate_check("some words", ""))

    def test_empty_text_returns_none(self):
        self.assertIsNone(qa._speech_rate_check("", "x.mp3"))

    @requires_ffmpeg
    def test_normal_rate_passes(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            audio = os.path.join(d, "a.m4a")
            # 10s of silence; 30 words -> 3.0 words/sec (in range)
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                            "anullsrc=r=44100:cl=mono", "-t", "10", audio],
                           capture_output=True, check=True)
            check = qa._speech_rate_check(" ".join(["word"] * 30), audio)
            self.assertEqual(check["status"], "pass")
            self.assertIn("3.0", check["detail"])

    @requires_ffmpeg
    def test_too_fast_warns_not_fails(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            audio = os.path.join(d, "a.m4a")
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                            "anullsrc=r=44100:cl=mono", "-t", "2", audio],
                           capture_output=True, check=True)
            check = qa._speech_rate_check(" ".join(["word"] * 40), audio)  # 20 wps
            self.assertEqual(check["status"], "warn")  # warn, never block


# ------------------------------------------------------- config validation
class ConfigTier23Tests(unittest.TestCase):
    def test_defaults_valid(self):
        self.assertEqual(config.validate_config(config.DEFAULTS), [])

    def test_new_keys_in_defaults(self):
        for key in ("topic_similarity_threshold", "localization_tier",
                    "publish_learning", "publish_learning_min_samples",
                    "loop_ending", "cover_frame", "engagement_drafts",
                    "auto_backup", "backup_keep"):
            self.assertIn(key, config.DEFAULTS)

    def test_threshold_out_of_range(self):
        c = dict(config.DEFAULTS)
        c["topic_similarity_threshold"] = 1.5
        self.assertTrue(any("topic_similarity_threshold" in e
                            for e in config.validate_config(c)))

    def test_bad_localization_tier(self):
        c = dict(config.DEFAULTS)
        c["localization_tier"] = "google"
        self.assertTrue(any("localization_tier" in e for e in config.validate_config(c)))

    def test_bad_language_code(self):
        c = dict(config.DEFAULTS)
        c["language"] = "english!"
        self.assertTrue(any("language" in e for e in config.validate_config(c)))

    def test_valid_language_region(self):
        c = dict(config.DEFAULTS)
        c["language"] = "es-MX"
        self.assertEqual(config.validate_config(c), [])

    def test_bool_keys_enforced(self):
        c = dict(config.DEFAULTS)
        c["publish_learning"] = "yes"
        self.assertTrue(any("publish_learning" in e for e in config.validate_config(c)))


# ------------------------------------------------------- upload language wiring
class UploadLanguageTests(unittest.TestCase):
    def test_plan_sets_language_fields(self):
        out = upload.plan("v.mp4", "T", "D", "unlisted", language="es-MX")
        self.assertEqual(out["defaultLanguage"], "es-MX")
        self.assertEqual(out["defaultAudioLanguage"], "es-MX")

    def test_plan_localizations(self):
        loc = {"es-MX": {"title": "Título", "description": "Descripción"}}
        out = upload.plan("v.mp4", "T", "D", "unlisted", language="es-MX", localizations=loc)
        self.assertEqual(out["localizations"], loc)

    def test_plan_no_language_omits_fields(self):
        out = upload.plan("v.mp4", "T", "D", "unlisted")
        self.assertNotIn("defaultLanguage", out)
        self.assertNotIn("localizations", out)


# ------------------------------------------------------- loop ending / cover frame
class LoopEndingTests(unittest.TestCase):
    @requires_ffmpeg
    def test_loop_ending_preserves_duration_and_extracts_cover(self):
        import subprocess

        from src import video
        with tempfile.TemporaryDirectory() as d:
            audio = os.path.join(d, "n.m4a")
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                            "anullsrc=r=44100:cl=mono", "-t", "6", audio],
                           capture_output=True, check=True)
            script = {"topic": "Test topic", "hook": "A hook.",
                      "text": "A hook. Some narration text here for the test.",
                      "style": "general"}
            out = os.path.join(d, "o.mp4")
            video.build_video(script, audio, out, width=1080, height=1920,
                              loop_ending=True, cover_frame=True)
            self.assertTrue(os.path.exists(out))
            dur = float(subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", out],
                capture_output=True, text=True, check=True).stdout.strip())
            self.assertAlmostEqual(dur, 6.0, delta=0.3)
            self.assertTrue(os.path.exists(os.path.join(d, "o.cover.jpg")))

    def test_loop_ending_skips_landscape(self):
        from src import video
        # Landscape (long-form) must not get a Shorts loop ending.
        self.assertFalse(video._apply_loop_ending("missing.mp4", 10, 1920, 1080))

    def test_loop_ending_skips_short_duration(self):
        from src import video
        self.assertFalse(video._apply_loop_ending("missing.mp4", 1.0, 1080, 1920))


if __name__ == "__main__":
    unittest.main()
