"""Regression tests for the review fixes.

Pure-Python tests run everywhere; render/detector tests run when ffmpeg +
ffprobe are installed and are skipped otherwise (same convention as the
other test modules).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import config, music, qa, scheduler, script, seo, thumbnail, trends, upload
from src.review import analyse

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
requires_ffmpeg = unittest.skipUnless(
    HAS_FFMPEG, "ffmpeg and ffprobe are required for this regression")


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {(result.stderr or '')[-500:]}")
    return result


def _duration(path):
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path])
    return float(out.stdout.strip())


def _video_stream(path):
    import json
    out = _run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=sample_aspect_ratio,width,height",
                "-of", "json", path])
    return json.loads(out.stdout)["streams"][0]


# ----------------------------------------------------------------- script.py
class ScriptLengthTests(unittest.TestCase):
    def test_long_scripts_do_not_repeat_one_filler_line_dozens_of_times(self):
        for builder in (script.build_history_long_script, script.build_long_script):
            s = builder("a test topic")
            self.assertGreaterEqual(s["word_count"], 1200)
            self.assertLessEqual(s["word_count"], 1800)
            sentences = [x.strip() for x in s["text"].split(".") if len(x.split()) > 8]
            most_common = Counter(sentences).most_common(1)[0][1]
            self.assertLessEqual(most_common, 2, "a filler line is repeated too many times")

    def test_long_scripts_keep_the_cta_at_the_end(self):
        for builder in (script.build_history_long_script, script.build_long_script):
            s = builder("a test topic")
            self.assertTrue(s["text"].rstrip().endswith(s["cta"].rstrip()))

    def test_history_short_honours_target_and_keeps_ending(self):
        s = script.build_history_short_script("a test topic", target_words=150)
        self.assertLessEqual(s["word_count"], 165)  # ~60s at 150 wpm + tolerance
        self.assertTrue(s["text"].rstrip().endswith(s["cta"].rstrip()))
        small = script.build_history_short_script("a test topic", target_words=75)
        self.assertLess(small["word_count"], s["word_count"])
        self.assertTrue(small["text"].rstrip().endswith(small["cta"].rstrip()))


# ----------------------------------------------------------------- config.py
class ConfigParserTests(unittest.TestCase):
    def _load(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write(text)
            path = fh.name
        try:
            return config.load_config(path)
        finally:
            os.unlink(path)

    def test_inline_comments_are_stripped(self):
        c = self._load('narrator_speed: 1.2 # faster\nniche: "history"  # note\n')
        self.assertEqual(c["narrator_speed"], 1.2)
        self.assertIsInstance(c["narrator_speed"], float)
        self.assertEqual(c["niche"], "history")

    def test_flow_style_lists_parse_as_lists(self):
        c = self._load("niches: []\npeak_windows: [a, b]\n")
        self.assertEqual(c["niches"], [])
        self.assertEqual(c["peak_windows"], ["a", "b"])

    def test_hash_inside_quotes_is_not_a_comment(self):
        c = self._load('url: "http://x.com/#frag"\n')
        self.assertEqual(c["url"], "http://x.com/#frag")


# ----------------------------------------------------------------- trends.py
class DedupeTests(unittest.TestCase):
    def test_merged_sources_have_no_duplicates(self):
        a = trends.base_entry("youtube", "Same Title", published="2026-11-20", engagement=100)
        b = trends.base_entry("reddit", "Same Title", published="2026-11-25", engagement=100000)
        c = trends.base_entry("google", "Same Title", published="2026-11-26")
        out = trends.dedupe([a, b, c])
        self.assertEqual(len(out), 1)
        merged = out[0]["merged_sources"]
        self.assertEqual(len(merged), len(set(merged)))
        self.assertEqual(set(merged), {"youtube", "reddit", "google"})


# --------------------------------------------------------------- scheduler.py
class SchedulerStaggerTests(unittest.TestCase):
    def test_after_forces_distinct_windows_per_format(self):
        cfg = config.load_config("config.yaml")
        now = datetime(2026, 11, 27, 6, 0, tzinfo=ZoneInfo("America/Chicago"))
        niche = "history mysteries investigated with modern tech"
        first, _ = scheduler.next_peak_window(niche, cfg, now=now, fmt="short")
        second, _ = scheduler.next_peak_window(niche, cfg, now=now, fmt="short", after=first)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertGreater(second, first)


# -------------------------------------------------------------------- qa.py
class QADetectorTests(unittest.TestCase):
    @requires_ffmpeg
    def test_silencedetect_finds_a_long_gap(self):
        with tempfile.TemporaryDirectory() as d:
            gap = os.path.join(d, "gap.m4a")
            _run(["ffmpeg", "-y", "-v", "error",
                  "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                  "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=6",
                  "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                  "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
                  "-c:a", "aac", gap])
            segments = qa.detect(gap, "silencedetect", "noise=-40dB", 2.0)
            self.assertTrue(segments, "the 6s silent gap was not detected")
            self.assertGreaterEqual(segments[0][1], 5.0)

    @requires_ffmpeg
    def test_detector_raises_on_bad_input_instead_of_passing(self):
        with tempfile.TemporaryDirectory() as d:
            img = os.path.join(d, "img.png")
            _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                  "-i", "color=c=red:s=64x64", "-frames:v", "1", img])
            with self.assertRaises(RuntimeError):
                qa.detect(img, "silencedetect", "noise=-40dB", 2.0)


# ------------------------------------------------------------------ video.py
@requires_ffmpeg
class VideoRenderTests(unittest.TestCase):
    def _assets(self, d):
        from src import video
        audio = os.path.join(d, "narr.m4a")
        _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
              "-i", "sine=frequency=440:duration=20", "-c:a", "aac", audio])
        clips = []
        for i, src in enumerate(("testsrc", "testsrc2")):
            clip = os.path.join(d, f"clip{i}.mp4")
            _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                  "-i", f"{src}=s=320x568:r=30:d=12", "-c:v", "libx264",
                  "-pix_fmt", "yuv420p", clip])
            clips.append(clip)
        return video, audio, clips

    def test_crossfade_does_not_truncate_narration(self):
        with tempfile.TemporaryDirectory() as d:
            video, audio, clips = self._assets(d)
            out = os.path.join(d, "out.mp4")
            video.build_video({"text": "Narration sentence. " * 30,
                               "topic": "clip test", "hook": "A hook."},
                              audio, out, visuals=clips, duration=20,
                              bitrate="300k", width=320, height=568,
                              min_resolution=1)
            # Old bug: 20s narration rendered to 19.5s (xfade ate the tail).
            self.assertAlmostEqual(_duration(out), 20.0, delta=0.6)

    def test_output_has_square_pixels(self):
        with tempfile.TemporaryDirectory() as d:
            video, audio, clips = self._assets(d)
            out = os.path.join(d, "out.mp4")
            video.build_video({"text": "Narration sentence. " * 30,
                               "topic": "clip test", "hook": "A hook."},
                              audio, out, visuals=clips, duration=20,
                              bitrate="300k", width=320, height=568,
                              min_resolution=1)
            self.assertEqual(_video_stream(out)["sample_aspect_ratio"], "1:1")


# ------------------------------------------------------------------ music.py
class MusicMatchTests(unittest.TestCase):
    def test_genre_or_mood_qualifies_a_track(self):
        track = {"genre": "pop", "mood": "upbeat", "tempo_bpm": 125}
        score, qualifies, _ = music.score_track(track, {"genre": "pop", "mood": "upbeat"})
        self.assertTrue(qualifies)
        self.assertGreater(score, 0)
        _, qualifies_off, _ = music.score_track(track, {"genre": "metal", "mood": "dark"})
        self.assertFalse(qualifies_off)


# ----------------------------------------------------------------- upload.py
class UploadPlanTests(unittest.TestCase):
    def test_publish_at_forces_private_in_dry_run_plan(self):
        plan = upload.plan("v.mp4", "T", "D", "unlisted",
                           publish_at="2026-11-27T18:00:00+00:00")
        self.assertEqual(plan["privacyStatus"], "private")
        self.assertIn("publishAt", plan)

    def test_no_publish_at_keeps_privacy(self):
        plan = upload.plan("v.mp4", "T", "D", "unlisted")
        self.assertEqual(plan["privacyStatus"], "unlisted")


# ----------------------------------------------------------------- review.py
class ReviewAnalyseTests(unittest.TestCase):
    def test_top_and_bottom_do_not_overlap_with_few_videos(self):
        videos = [{"title": f"v{i}", "views": 100 - i} for i in range(5)]
        scored, no_data, top, bottom, median, shared = analyse(videos)
        top_ids = {v["title"] for v in top}
        bottom_ids = {v["title"] for v in bottom}
        self.assertFalse(top_ids & bottom_ids, "top and bottom performers overlap")

    def test_three_videos_have_no_false_bottom(self):
        videos = [{"title": f"v{i}", "views": 100 - i} for i in range(3)]
        _, _, top, bottom, _, _ = analyse(videos)
        self.assertEqual(len(top), 3)
        self.assertEqual(bottom, [])


# --------------------------------------------------------------- thumbnail.py
class ThumbnailClaimTests(unittest.TestCase):
    def test_whole_word_matching_rejects_substring_false_positive(self):
        ok, _ = thumbnail.validate_claim("art", "let us start here", topic="")
        self.assertFalse(ok, "'art' should not match inside 'start'")
        ok_true, _ = thumbnail.validate_claim("start", "let us start here", topic="")
        self.assertTrue(ok_true)


# -------------------------------------------------------------------- seo.py
class SeoTitleTests(unittest.TestCase):
    def test_history_style_uses_history_titles(self):
        s = {"topic": "a lost city that maps cannot place",
             "style": "history_mystery", "hook_style": "question", "hook": "h", "cta": "c"}
        entry = seo.build_entry(s, {}, "long")
        joined = " ".join(entry["titles"]).lower()
        self.assertNotIn("simple system", joined)
        self.assertNotIn("stop starting over", joined)


if __name__ == "__main__":
    unittest.main()
