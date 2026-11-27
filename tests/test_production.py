"""Regression tests for the production-quality roadmap (Phases 1-3 + polish).

Pure-Python tests run everywhere; render tests run when ffmpeg + ffprobe
are installed and are skipped otherwise (same convention as the other
test modules). PIL-dependent checks are skipped when Pillow is absent so
the stdlib-only suite stays green.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import brand, cache, config, models, research, script, thumbnail, trends, video
from src.review import hook_style_performance

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
requires_ffmpeg = unittest.skipUnless(HAS_FFMPEG, "ffmpeg + ffprobe required")
try:
    import PIL  # noqa: F401
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
requires_pil = unittest.skipUnless(HAS_PIL, "Pillow required")


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {(r.stderr or '')[-400:]}")
    return r


# ----------------------------------------------------------- Phase 1: captions
class KaraokeCaptionTests(unittest.TestCase):
    def _words(self, n=12):
        return [{"text": f"word{i}", "start": i * 0.4, "end": i * 0.4 + 0.35}
                for i in range(n)]

    def test_word_timings_highlight_active_word_in_accent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.ass")
            video.make_ass("x", 5, path, width=1080, height=1920,
                           timings={"words": self._words()},
                           brand=models.Brand(accent="#FFCB05"))
            data = Path(path).read_text(encoding="utf-8")
            # ASS accent colour for #FFCB05 is &H0005CBFF (AABBGGRR).
            self.assertIn("{\\c&H0005CBFF}", data)
            self.assertGreater(sum(1 for l in data.splitlines()
                                   if l.startswith("Dialogue")), 5)

    def test_safe_zone_keeps_captions_above_bottom_quarter(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.ass")
            video.make_ass("x", 5, path, width=1080, height=1920,
                           timings={"words": self._words()}, safe_zone=0.25)
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            style = next(l for l in lines if l.startswith("Style:"))
            margin_v = int(style.split(",")[-2])
            self.assertGreaterEqual(margin_v, int(1920 * 0.25))

    def test_no_timings_falls_back_to_even_chunks(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.ass")
            video.make_ass("one two three four five six seven eight", 4, path)
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            events = [l for l in lines if l.startswith("Dialogue")]
            self.assertTrue(events)
            self.assertIn("one two three", events[0])

    def test_load_timings_reads_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            audio = os.path.join(d, "a.mp3")
            Path(audio).write_bytes(b"\0")
            self.assertIsNone(video.load_timings(audio))
            with open(audio + ".timings.json", "w") as fh:
                json.dump({"words": self._words()}, fh)
            self.assertTrue(video.load_timings(audio)["words"])


# ------------------------------------------------------------- Phase 1: brand
class BrandTests(unittest.TestCase):
    def test_hex_to_rgb_and_shorthand(self):
        self.assertEqual(brand.hex_to_rgb("#FFCB05"), (255, 203, 5))
        self.assertEqual(brand.hex_to_rgb("#FC5"), (255, 204, 85))
        self.assertEqual(brand.hex_to_rgb("zzz", (1, 2, 3)), (1, 2, 3))

    def test_ass_and_drawtext_color_forms(self):
        self.assertEqual(brand.ass_color("#FFCB05"), "&H0005CBFF")
        self.assertEqual(brand.drawtext_color("#FFCB05"), "0xFFCB05")

    def test_brand_from_config_defaults(self):
        b = models.Brand.from_config({"brand": {"accent": "#123456"}})
        self.assertEqual(b.accent, "#123456")
        self.assertEqual(b.font, "DejaVu Sans")  # missing key -> default


# ------------------------------------------------------------- Phase 1: models
class ModelTests(unittest.TestCase):
    def test_script_round_trip_preserves_fields(self):
        data = {"rank": 1, "topic": "t", "text": "hello world", "format": "short",
                "style": "history_mystery", "sections": [{"title": "s", "tier": "KNOWN"}],
                "custom_field": 42}
        s = models.Script.from_dict(data)
        out = s.to_dict()
        self.assertEqual(out["text"], "hello world")
        self.assertEqual(out["format"], "short")
        self.assertEqual(out["custom_field"], 42)
        self.assertEqual(s.cache_key(), models.content_hash("hello world"))

    def test_video_report_pass_rate(self):
        r = models.VideoReport(overall="pass", checks=[
            {"status": "pass"}, {"status": "pass"}, {"status": "fail"}])
        self.assertTrue(r.passed)
        self.assertAlmostEqual(r.pass_rate, 2 / 3)

    def test_source_from_string_flags_no_public_url(self):
        s = models.Source.from_dict("A book")
        self.assertTrue(s.no_public_url)
        self.assertIsNone(s.url)


# ------------------------------------------------------------- Phase 3: cache
class CacheTests(unittest.TestCase):
    def test_key_is_stable_and_order_sensitive(self):
        self.assertEqual(cache.make_key("a", "b", 1), cache.make_key("a", "b", 1))
        self.assertNotEqual(cache.make_key("a", "b"), cache.make_key("b", "a"))

    def test_hit_only_when_output_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            cpath = os.path.join(d, "cache.json")
            out = os.path.join(d, "out.mp4")
            Path(out).write_bytes(b"video")
            key = cache.make_key("script", "voice")
            self.assertFalse(cache.is_cached("video", key, out, cpath))
            cache.mark_cached("video", key, out, cpath)
            self.assertTrue(cache.is_cached("video", key, out, cpath))
            Path(out).write_bytes(b"different")  # changed -> miss
            self.assertFalse(cache.is_cached("video", key, out, cpath))


# ---------------------------------------------------------- Phase 2: research
class ResearchTests(unittest.TestCase):
    def test_parse_summary_facts_and_shock_are_sourced(self):
        summary = {"title": "Thing", "extract":
                   "Thing is old. It was found in 1901. Nobody knows why.",
                   "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Thing"}}}
        p = research.parse_summary(summary)
        self.assertEqual(len(p["facts"]), 3)
        self.assertTrue(all(f["source"]["url"] for f in p["facts"]))
        self.assertIsNotNone(p["shock_candidate"])
        self.assertIn("1901", p["shock_candidate"]["text"])

    def test_parse_wikidata_literal_value(self):
        data = {"entities": {"Q1": {"labels": {"en": {"value": "X"}},
                "claims": {"P571": [{"mainsnak": {"datavalue":
                    {"type": "time", "value": {"time": "+1850-00-00T00:00:00Z"}}}}]}}}}
        facts = research.parse_wikidata(data, "Q1")
        self.assertEqual(len(facts), 1)
        self.assertIn("1850", facts[0]["text"])
        self.assertTrue(facts[0]["source"]["url"].endswith("Q1"))

    def test_llm_template_tier_is_offline_and_sourced(self):
        facts = [{"text": "A fact.", "source": {"title": "W", "url": "http://x"}}]
        draft = research.llm_draft("topic", facts, tier="template")
        self.assertEqual(draft["tier"], "template")
        self.assertIn("A fact.", draft["text"])
        self.assertEqual(draft["sources"][0]["url"], "http://x")

    def test_research_topic_graceful_on_network_failure(self):
        original = research._get_json
        research._get_json = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
        try:
            result = research.research_topic("anything")
            self.assertEqual(result["provider"], "none")
            self.assertEqual(result["facts"], [])
        finally:
            research._get_json = original

    def test_apply_research_fills_sources_and_shock(self):
        s = script.build_history_short_script("a lost city")
        self.assertIsNone(s["shock_hook"])  # no candidate shock supplied
        research_result = {"provider": "wikipedia+wikidata",
                           "facts": [{"text": "Verified fact.", "tier": "KNOWN",
                                      "source": {"title": "Wikipedia", "url": "http://x"}}],
                           "sources": [{"title": "Wikipedia", "url": "http://x"}],
                           "shock_candidate": {"text": "Surprising true fact.", "tier": "KNOWN",
                                               "source": {"title": "Wikipedia", "url": "http://x"}}}
        out = script.apply_research(s, research_result)
        self.assertEqual(out["shock_hook"]["text"], "Surprising true fact.")
        self.assertEqual(out["sources"][0]["url"], "http://x")
        self.assertEqual(out["hook"], "Surprising true fact.")


# ------------------------------------------------------- Phase 2: topic memory
class TopicMemoryTests(unittest.TestCase):
    def test_recent_topic_detected_and_old_one_not(self):
        now = datetime(2026, 11, 27, tzinfo=timezone.utc)
        history = [{"topic": "Lost City", "date": (now - timedelta(days=5)).isoformat()},
                   {"topic": "Old Story", "date": (now - timedelta(days=60)).isoformat()}]
        self.assertTrue(script.is_recent_topic("lost city", history, days=30, now=now))
        self.assertFalse(script.is_recent_topic("old story", history, days=30, now=now))
        self.assertFalse(script.is_recent_topic("brand new", history, days=30, now=now))

    def test_record_topics_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hist.json")
            script.record_topics(["A", "B"], path=path)
            hist = script.load_topic_history(path)
            self.assertEqual({h["topic"] for h in hist}, {"A", "B"})


# --------------------------------------------------------- Phase 2: hook variants
class HookVariantTests(unittest.TestCase):
    def test_all_four_variants_generated(self):
        v = script.hook_variants("saving money")
        self.assertEqual(set(v), set(script.HOOK_STYLES))
        self.assertTrue(all("saving money" in h for h in v.values()))

    def test_select_hook_style_prefers_review_winner(self):
        self.assertEqual(script.select_hook_style({"review_preferred_hook_style": "shock"}), "shock")
        self.assertEqual(script.select_hook_style({}, explicit="story"), "story")
        self.assertEqual(script.select_hook_style({"review_preferred_hook_style": "bogus"}), "statement")

    def test_review_ranks_hooks_by_views(self):
        videos = [{"hook_style": "question", "views": 100},
                  {"hook_style": "shock", "views": 500},
                  {"hook_style": "question", "views": 50}]
        ranking = hook_style_performance(videos)
        self.assertEqual(ranking[0]["hook_style"], "shock")
        self.assertEqual(ranking[0]["total_views"], 500)


# --------------------------------------------------------- Phase 2: trend velocity
class TrendVelocityTests(unittest.TestCase):
    def test_velocity_component_present_for_recent_viral(self):
        e = trends.base_entry("youtube", "Viral", published="2026-11-25", engagement=100000)
        self.assertIn("velocity_per_day", e["score_breakdown"])
        self.assertGreater(e["score_breakdown"]["velocity_log"], 0)

    def test_recency_decays_smoothly(self):
        recent, _ = trends._recency_bonus("2026-11-26")
        old, _ = trends._recency_bonus("2026-10-01")
        self.assertGreater(recent, old)
        self.assertGreater(old, 0)  # exponential, not a hard zero cliff


# ------------------------------------------------------------- Phase 2: scene B-roll
class SceneBrollTests(unittest.TestCase):
    def test_section_keywords_derived_from_titles(self):
        s = {"topic": "ancient egypt", "sections": [
            {"title": "The mystery of the pyramids"},
            {"title": "What the evidence actually shows"}]}
        kw = video.section_keywords(s)
        self.assertEqual(len(kw), 2)
        self.assertTrue(all(isinstance(k, str) and k for k in kw))

    def test_no_key_returns_empty(self):
        os.environ.pop("PEXELS_API_KEY", None)
        os.environ.pop("PIXABAY_API_KEY", None)
        self.assertEqual(video.fetch_scene_stock({}, {"topic": "x", "sections": []}), [])


# ------------------------------------------------------------- polish: thumbnail
class ThumbnailSaliencyTests(unittest.TestCase):
    def test_focal_centered_on_uniform_energy(self):
        self.assertEqual(thumbnail.focal_from_energy([1, 1, 1, 1]), 0.5)

    def test_focal_biases_toward_subject(self):
        self.assertGreater(thumbnail.focal_from_energy([0, 0, 0, 10]), 0.6)
        self.assertLess(thumbnail.focal_from_energy([10, 0, 0, 0]), 0.4)

    @requires_pil
    def test_saliency_crop_runs(self):
        from PIL import Image
        img = Image.new("RGB", (400, 300), (10, 10, 10))
        for x in range(300, 400):  # bright subject on the right
            for y in range(300):
                img.putpixel((x, y), (255, 255, 255))
        crop = thumbnail._fill_crop(img, 200, 200, focal="saliency")
        self.assertEqual(crop.size, (200, 200))


# ------------------------------------------------------------- Phase 3: config
class ConfigValidationTests(unittest.TestCase):
    def test_validate_catches_bad_types(self):
        errors = config.validate_config({"narrator_speed": "fast", "niches": "x",
                                         "series_enabled": "yes"})
        self.assertTrue(any("narrator_speed" in e for e in errors))
        self.assertTrue(any("niches" in e for e in errors))
        self.assertTrue(any("series_enabled" in e for e in errors))

    def test_validate_passes_good_config(self):
        self.assertEqual(config.validate_config(config.load_config("config.yaml")), [])

    def test_nested_brand_parses_in_fallback(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write('brand:\n  accent: "#FF0000"\n  font: "DejaVu Serif"\n')
            path = fh.name
        try:
            c = config._load_yaml_fallback(Path(path).read_text().splitlines(keepends=True))
            self.assertEqual(c["brand"]["accent"], "#FF0000")
            self.assertEqual(c["brand"]["font"], "DejaVu Serif")
        finally:
            os.unlink(path)


# ------------------------------------------------------------- Phase 3: CLI
class CliTests(unittest.TestCase):
    def test_no_command_prints_help_and_returns_zero(self):
        from src import cli
        self.assertEqual(cli.main([]), 0)

    def test_commands_map_to_importable_modules(self):
        import importlib

        from src import cli
        for _name, mod in cli.COMMANDS.items():
            self.assertTrue(importlib.import_module(mod))


# ------------------------------------------------------------- Phase 1: music
class MusicMasteringTests(unittest.TestCase):
    def test_carry_timings_copies_sidecar(self):
        from src import music
        with tempfile.TemporaryDirectory() as d:
            narr = os.path.join(d, "n.mp3")
            out = os.path.join(d, "m.mp3")
            Path(narr).write_bytes(b"\0")
            with open(narr + ".timings.json", "w") as fh:
                json.dump({"words": []}, fh)
            music._carry_timings(narr, out)
            self.assertTrue(os.path.exists(out + ".timings.json"))

    @requires_ffmpeg
    def test_no_music_path_masters_loudness(self):
        from src import music
        with tempfile.TemporaryDirectory() as d:
            narr = os.path.join(d, "n.mp3")
            out = os.path.join(d, "m.mp3")
            _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                  "-i", "sine=frequency=440:duration=3", "-c:a", "libmp3lame", narr])
            cwd = os.getcwd()
            os.chdir(d)  # keep music's run-log append inside the temp dir
            try:
                rc = music.main(["--narration", narr, "--output", out,
                                 "--config", "/nonexistent.yaml"])
            finally:
                os.chdir(cwd)
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
