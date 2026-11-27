"""Regression tests for the Tier 1 feedback loop + trust features:
retention analytics, upload verification + video-ID feedback, and
on-screen source citations. Pure-Python where possible; render checks
are gated on ffmpeg.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import analytics, config, upload, video

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
requires_ffmpeg = unittest.skipUnless(HAS_FFMPEG, "ffmpeg + ffprobe required")


# ---------------------------------------------------- retention analytics
class AnalyticsTests(unittest.TestCase):
    def test_parse_retention_report_maps_metrics(self):
        report = {"columnHeaders": [{"name": "video"}, {"name": "averageViewDuration"},
                                    {"name": "averageViewPercentage"}, {"name": "views"}],
                  "rows": [["abc", 42, 55.5, 1000]]}
        out = analytics.parse_retention_report(report)
        self.assertEqual(out[0]["video_id"], "abc")
        self.assertEqual(out[0]["avg_view_duration_seconds"], 42)
        self.assertEqual(out[0]["retention_pct"], 55.5)

    def test_parse_empty_or_no_video_dimension(self):
        self.assertEqual(analytics.parse_retention_report({}), [])
        self.assertEqual(analytics.parse_retention_report(
            {"columnHeaders": [{"name": "day"}], "rows": [["2026-11-01"]]}), [])

    def test_enrich_disabled_is_noop(self):
        videos = [{"video_id": "abc", "retention_pct": None}]
        self.assertEqual(analytics.enrich_with_retention(videos, {"analytics_enabled": False}), videos)

    def test_enrich_fills_retention_from_analytics(self):
        videos = [{"video_id": "abc", "retention_pct": None, "avg_view_duration_seconds": None}]
        original = analytics.fetch_retention
        analytics.fetch_retention = lambda *a, **k: [
            {"video_id": "abc", "retention_pct": 61.0, "avg_view_duration_seconds": 30}]
        try:
            out = analytics.enrich_with_retention(videos, {"analytics_enabled": True})
            self.assertEqual(out[0]["retention_pct"], 61.0)
            self.assertEqual(out[0]["avg_view_duration_seconds"], 30)
        finally:
            analytics.fetch_retention = original

    def test_enrich_keeps_existing_manual_retention(self):
        videos = [{"video_id": "abc", "retention_pct": 90.0}]
        original = analytics.fetch_retention
        analytics.fetch_retention = lambda *a, **k: [{"video_id": "abc", "retention_pct": 10.0}]
        try:
            out = analytics.enrich_with_retention(videos, {"analytics_enabled": True})
            self.assertEqual(out[0]["retention_pct"], 90.0)  # manual wins
        finally:
            analytics.fetch_retention = original


# ---------------------------------------------------- upload verification
class UploadVerificationTests(unittest.TestCase):
    def test_interpret_status_states(self):
        self.assertEqual(upload.interpret_upload_status(
            {"items": [{"status": {"uploadStatus": "processed"}}]})[0], "processed")
        self.assertEqual(upload.interpret_upload_status(
            {"items": [{"status": {"uploadStatus": "failed", "failureReason": "codec"}}]})[0], "failed")
        self.assertEqual(upload.interpret_upload_status(
            {"items": [{"status": {"uploadStatus": "rejected"}}]})[0], "rejected")
        self.assertEqual(upload.interpret_upload_status(
            {"items": [{"status": {"uploadStatus": "processing"}}]})[0], "processing")
        self.assertEqual(upload.interpret_upload_status({})[0], "unknown")

    def _fake_yt(self, statuses):
        seq = iter(statuses)

        class Videos:
            def list(self, **k):
                state = next(seq)

                class R:
                    def execute(inner):
                        return {"items": [{"status": {"uploadStatus": state}}]}
                return R()

        class YT:
            def videos(self):
                return Videos()
        return YT()

    def test_verify_polls_until_processed(self):
        yt = self._fake_yt(["processing", "processing", "processed"])
        state, _ = upload.verify_processed(yt, "vid", timeout=5, interval=0, sleep=lambda s: None)
        self.assertEqual(state, "processed")

    def test_verify_raises_on_rejected(self):
        yt = self._fake_yt(["rejected"])
        with self.assertRaises(RuntimeError):
            upload.verify_processed(yt, "vid", timeout=1, interval=0, sleep=lambda s: None)

    def test_record_feedback_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "feedback.json")
            upload.record_upload_feedback({"video_id": "a", "topic": "t1"}, path)
            upload.record_upload_feedback({"video_id": "b", "topic": "t2"}, path)
            import json
            data = json.loads(Path(path).read_text())
            self.assertEqual([e["video_id"] for e in data], ["a", "b"])


# ---------------------------------------------------- on-screen citations
class CitationTests(unittest.TestCase):
    def _script(self):
        return {"style": "history_mystery", "topic": "Antikythera mechanism",
                "text": "word " * 100, "hook": "A hook.",
                "cta": "What do you think happened?",
                "sources": [{"title": "Wikipedia: Thing", "url": "http://x"}],
                "shock_hook": {"text": "Fact.", "source": {"title": "Wikipedia: Thing", "url": "http://x"}},
                "sections": [{"title": "Evidence", "tier": "KNOWN", "text": "w " * 40},
                             {"title": "Theories", "tier": "DEBATED", "text": "w " * 40}]}

    def test_real_source_title_rejects_placeholder(self):
        self.assertEqual(video._real_source_title({"title": "placeholder — do NOT publish"}), "")
        self.assertEqual(video._real_source_title({"title": "Wikipedia: Thing"}), "Wikipedia: Thing")
        self.assertEqual(video._real_source_title(""), "")

    def test_citations_emitted_for_history_with_sources(self):
        with tempfile.TemporaryDirectory() as d:
            filters = video._citation_lower_thirds(
                self._script(), 20, d, 1080, 1920, "DejaVu Sans", "0xFFFFFF",
                "0x000000", "0xFFCB05", 72)
            self.assertTrue(filters)
            texts = [Path(p).read_text() for p in Path(d).glob("cite_*.txt")]
            self.assertTrue(any(t.startswith("Source: ") for t in texts))
            self.assertTrue(any("Wikipedia: Thing" in t for t in texts))

    def test_no_citations_for_non_history(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(video._citation_lower_thirds(
                {"style": "general"}, 20, d, 1080, 1920, "f", "w", "b", "a", 72), [])

    def test_no_citations_without_real_source(self):
        with tempfile.TemporaryDirectory() as d:
            s = self._script()
            s["sources"] = ["placeholder — do NOT publish"]
            s["shock_hook"] = None
            self.assertEqual(video._citation_lower_thirds(
                s, 20, d, 1080, 1920, "f", "w", "b", "a", 72), [])

    @requires_ffmpeg
    def test_history_render_with_citations_is_valid(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            audio = os.path.join(d, "a.m4a")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", "sine=frequency=440:duration=10", "-c:a", "aac", audio],
                           capture_output=True, check=True)
            out = os.path.join(d, "out.mp4")
            video.build_video(self._script(), audio, out, visuals=[], duration=10,
                              bitrate="300k", width=320, height=568, show_citations=True)
            self.assertTrue(os.path.exists(out))


# ---------------------------------------------------- config wiring
class Tier1ConfigTests(unittest.TestCase):
    def test_new_defaults_present_and_valid(self):
        c = config.load_config("config.yaml")
        self.assertIn("analytics_enabled", c)
        self.assertIn("verify_upload", c)
        self.assertIn("show_citations", c)
        self.assertEqual(config.validate_config(c), [])

    def test_validation_catches_bad_tier1_types(self):
        errors = config.validate_config({"analytics_enabled": "yes", "upload_process_timeout": "slow"})
        self.assertTrue(any("analytics_enabled" in e for e in errors))
        self.assertTrue(any("upload_process_timeout" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
