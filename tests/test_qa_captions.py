"""Regression tests for the QA caption checks (F4, Phase 2 Worker B).

The old QA caption check was existence-only (src/qa.py:200-207):
it passed if the .ass file existed and was non-empty. These tests
pin the replacement -- captions_cover_script, captions_cover_duration
and captions_timing, each reported as its own QA check:

- truncated .ass (3 events) for a 60 s video -> caption checks FAIL
- stale .ass (all events shifted +10 s) -> captions_timing FAILS
  (while captions_cover_script still passes: the words are right,
  only the timing is wrong)
- missing .ass -> caption checks FAIL (not pass)
- no script words supplied -> captions_cover_script FAILS (fail-closed)
- the real v2 Short's .ass + word timings -> all caption checks PASS

Grounding: the v2 Short's real .ass
(productions/antikythera-short-2026-11-15-v2/...mp4.ass, 53 events:
51 body events covering the 151-word script + 2 subscribe-close
extra events) and its real word timings (word_timings_final.json).
The production v2 MP4 (80 MB) and mixed-audio.mp3 (63.6 s) are NOT
in the repo, so the valid-v2 check() test synthesizes a video track
and narration of the same 63.6 s and runs the real check() against
the real .ass (see test_valid_v2_ass_passes_via_real_check). NOTE:
never run run_qa() against the production v2 MP4 in place -- a
failing check would trigger the auto-fix re-render and overwrite it.
The check()-level test below is read-only; run_qa is exercised only
on throwaway tmp videos.

Fixture-based, no network. Real-ffmpeg tests skip cleanly without
ffmpeg. The valid-v2 check() test takes ~1-2 min; the rest are small
synthetic videos.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import qa
from src.caption_validation import (
    check_cover_duration, check_cover_script, check_timing, parse_ass)
from src.video import make_ass

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2 = os.path.join(REPO_ROOT, "productions",
                  "antikythera-short-2026-11-15-v2")
V2_MP4 = os.path.join(V2, "DeepScan-Antikythera-Short-2026-11-15-v2.mp4")
V2_ASS = V2_MP4 + ".ass"
V2_TIMINGS = os.path.join(V2, "word_timings_final.json")


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {(result.stderr or '')[-500:]}")
    return result


def _write_sine_mp3(path, seconds):
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
          f"sine=frequency=440:duration={seconds}", "-c:a", "libmp3lame",
          "-b:a", "128k", path])


def _write_test_video(path, seconds, audio):
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
          f"testsrc2=size=320x240:rate=30:duration={seconds}",
          "-i", audio, "-c:v", "libx264", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-shortest", path])


def _status(checks, name):
    found = [c for c in checks if c["check"] == name]
    assert len(found) == 1, f"check {name} must appear exactly once: {checks}"
    return found[0]["status"]


def _script_words():
    with open(os.path.join(V2, "narration.txt"), encoding="utf-8") as fh:
        return fh.read().strip().split()


def _write_manual_ass(path, events):
    """Write a minimal .ass with the given (start, end, text) events."""
    def fmt(t):
        h, rem = divmod(int(t), 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}.{int((t % 1) * 100):02d}"

    lines = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080",
             "PlayResY: 1920", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, "
             "Bold, Alignment, MarginL, MarginR, MarginV, BorderStyle, Outline",
             "Style: Default,DejaVu Sans,72,&H00FFFFFF,&H80000000,-1,2,60,60,400,1,5",
             "", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
             "MarginV, Effect, Text"]
    for start, end, text in events:
        lines.append(f"Dialogue: 0,{fmt(start)},{fmt(end)},Default,,0,0,0,,{text}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _write_shifted_ass(src, dst, shift):
    """Copy an .ass shifting every Dialogue event by `shift` seconds."""
    def fmt(t):
        h, rem = divmod(int(t), 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}.{int((t % 1) * 100):02d}"

    def parse(t):
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    out = []
    with open(src, encoding="utf-8") as fh:
        src_lines = fh.readlines()
    for line in src_lines:
        if line.startswith("Dialogue:"):
            fields = line.split("Dialogue:", 1)[1].strip().split(",", 9)
            fields[1] = fmt(parse(fields[1]) + shift)
            fields[2] = fmt(parse(fields[2]) + shift)
            out.append("Dialogue: " + ",".join(fields))
        else:
            out.append(line.rstrip("\n"))
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))


class CaptionHelperTests(unittest.TestCase):
    """Pure-helper tests on the real v2 .ass (fast, no ffmpeg)."""

    def test_valid_v2_ass_passes_all_caption_checks(self):
        events = parse_ass(V2_ASS)
        words = _script_words()
        self.assertEqual(len(events), 53)  # 51 body + 2 subscribe-close
        self.assertEqual(len(words), 151)
        passed, detail = check_cover_script(events, words)
        self.assertTrue(passed, detail)
        passed, detail = check_cover_duration(events, 63.6)
        self.assertTrue(passed, detail)
        from src.caption_validation import load_word_timings
        timings = load_word_timings(V2_TIMINGS)
        passed, detail, verified = check_timing(events, words, timings, 63.6)
        self.assertTrue(verified, "timings supplied: must verify vs audio")
        self.assertTrue(passed, detail)

    def test_truncated_ass_fails_cover_and_duration(self):
        events = parse_ass(V2_ASS)[:3]
        words = _script_words()
        passed, detail = check_cover_script(events, words)
        self.assertFalse(passed, detail)
        self.assertIn("9/151", detail)
        passed, detail = check_cover_duration(events, 60.0)
        self.assertFalse(passed, detail)
        self.assertIn("last event ends", detail)

    def test_stale_ass_fails_timing_but_not_word_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            shifted = os.path.join(tmp, "stale.ass")
            _write_shifted_ass(V2_ASS, shifted, 10.0)
            events = parse_ass(shifted)
            words = _script_words()
            from src.caption_validation import load_word_timings
            timings = load_word_timings(V2_TIMINGS)
            # Words unchanged and in order: coverage still passes.
            passed, detail = check_cover_script(events, words)
            self.assertTrue(passed, detail)
            # Times are 10 s late: timing must fail.
            passed, detail, verified = check_timing(events, words, timings, 63.6)
            self.assertTrue(verified)
            self.assertFalse(passed, detail)

    def test_duplicated_word_fails_cover_script(self):
        events = parse_ass(V2_ASS)
        words = _script_words()
        # Duplicate the first body event's words right after it.
        dup = [events[0], events[0]] + events[1:]
        passed, detail = check_cover_script(dup, words)
        self.assertFalse(passed, detail)

    def test_out_of_order_words_fail_cover_script(self):
        events = parse_ass(V2_ASS)
        words = _script_words()
        swapped = [events[1], events[0]] + events[2:]
        passed, detail = check_cover_script(swapped, words)
        self.assertFalse(passed, detail)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class QaCaptionCheckTests(unittest.TestCase):
    """Tests through the real qa.check() path (small synthetic videos)."""

    def test_valid_v2_ass_passes_via_real_check(self):
        # The production v2 MP4 (80 MB) and mixed-audio.mp3 are NOT in
        # the repo, so qa.check() on them returns after file_exists and
        # the caption checks never run (run #260). Exercise the real
        # check() path with the real v2 .ass + script + word timings,
        # but a synthetic video track and narration of the same 63.6 s
        # duration the captions were timed against. The caption checks
        # only read the .ass, the script words, the timings and the
        # duration, so the video content is irrelevant to them.
        with open(os.path.join(V2, "narration.txt"),
                  encoding="utf-8") as fh:
            script = fh.read().strip()
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 63.6)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 63.6, audio)
            shutil.copy(V2_ASS, video + ".ass")
            checks, _ = qa.check(video, narration=audio,
                                 script_text=script, fmt="short",
                                 word_timings_path=V2_TIMINGS)
            self.assertEqual(_status(checks, "captions_cover_script"), "pass")
            self.assertEqual(_status(checks, "captions_cover_duration"), "pass")
            self.assertEqual(_status(checks, "captions_timing"), "pass")

    def test_truncated_ass_for_60s_video_fails(self):
        words = _script_words()
        script = " ".join(words)
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 60.0)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 60.0, audio)
            # 3 events covering only the first 9 script words, all in
            # the first 9 s of a 60 s video (a truncated .ass).
            ass = os.path.join(tmp, "v.mp4.ass")
            _write_manual_ass(ass, [
                (0.0, 3.0, "A GEARED BRONZE"),
                (3.0, 6.0, "MACHINE THAT PREDICTED"),
                (6.0, 9.0, "ECLIPSES EXISTED IN"),
            ])
            checks, _ = qa.check(video, narration=audio, script_text=script,
                                 fmt="short",
                                 word_timings_path=V2_TIMINGS)
            self.assertEqual(_status(checks, "captions_cover_script"), "fail")
            self.assertEqual(_status(checks, "captions_cover_duration"), "fail")
            self.assertEqual(_status(checks, "captions_timing"), "fail")

    def test_missing_ass_fails_caption_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 6.0)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 6.0, audio)
            checks, _ = qa.check(video, narration=audio,
                                 script_text="A geared bronze machine",
                                 fmt="short")
            self.assertEqual(_status(checks, "captions_present"), "fail")
            self.assertEqual(_status(checks, "captions_cover_script"), "fail")
            self.assertEqual(_status(checks, "captions_cover_duration"), "fail")
            self.assertEqual(_status(checks, "captions_timing"), "fail")

    def test_no_script_words_fails_cover_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 6.0)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 6.0, audio)
            ass = video + ".ass"
            make_ass("A geared bronze machine that predicted eclipses",
                     6.0, ass)
            # No script_text / script_words at all: fail-closed.
            checks, _ = qa.check(video, narration=audio, fmt="short")
            self.assertEqual(_status(checks, "captions_cover_script"), "fail")
            self.assertEqual(_status(checks, "captions_timing"), "fail")

    def test_stale_ass_fails_timing_via_real_check(self):
        script = "A geared bronze machine that predicted eclipses existed"
        timed = [(0.5 + i * 0.8, 0.5 + (i + 1) * 0.8, w)
                 for i, w in enumerate(script.split())]
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 12.0)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 12.0, audio)
            ass = video + ".ass"
            make_ass(script, 12.0, ass, word_timings=timed)
            timings_path = os.path.join(tmp, "timings.json")
            with open(timings_path, "w", encoding="utf-8") as fh:
                json.dump([list(t) for t in timed], fh)
            good, _ = qa.check(video, narration=audio, script_text=script,
                               fmt="short", word_timings_path=timings_path)
            self.assertEqual(_status(good, "captions_timing"), "pass")
            # Shift every event +10 s: stale captions from another cut.
            _write_shifted_ass(ass, ass, 10.0)
            stale, _ = qa.check(video, narration=audio, script_text=script,
                                fmt="short", word_timings_path=timings_path)
            self.assertEqual(_status(stale, "captions_timing"), "fail")
            # Word coverage is unaffected by the shift.
            self.assertEqual(_status(stale, "captions_cover_script"), "pass")

    def test_timing_without_timings_records_not_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 6.0)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 6.0, audio)
            ass = video + ".ass"
            make_ass("A geared bronze machine that predicted eclipses",
                     6.0, ass)
            checks, _ = qa.check(video, narration=audio,
                                 script_text="A geared bronze machine that "
                                             "predicted eclipses",
                                 fmt="short")
            found = [c for c in checks if c["check"] == "captions_timing"]
            self.assertEqual(found[0]["status"], "pass")
            self.assertIn("NOT verified", found[0]["detail"])

    def test_run_qa_autofix_regenerates_truncated_captions(self):
        # End-to-end through run_qa: a truncated .ass triggers the
        # caption re-render fix (fresh .ass from the script), while
        # the visual checks stay failed -- no manifest exists and a
        # gradient re-render cannot fix missing real visuals.
        script = ("A geared bronze machine that predicted eclipses "
                  "existed in the ancient world about two thousand "
                  "years ago today")
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.mp3")
            _write_sine_mp3(audio, 6.0)
            video = os.path.join(tmp, "v.mp4")
            _write_test_video(video, 6.0, audio)
            ass = video + ".ass"
            make_ass("A geared bronze machine", 6.0, ass)
            report = os.path.join(tmp, "qa_report.json")
            ok = qa.run_qa(video, narration=audio, script_text=script,
                           report_path=report, fmt="short")
            self.assertFalse(ok)
            with open(report, encoding="utf-8") as fh:
                data = json.load(fh)
            by_name = {c["check"]: c for c in data["checks"]}
            self.assertIn("re-rendered with fallback visuals + fresh captions",
                          " ".join(data["fixes_applied"]))
            self.assertEqual(by_name["captions_cover_script"]["status"], "pass")
            self.assertEqual(by_name["real_visuals_present"]["status"], "fail")
            self.assertEqual(by_name["visual_coverage"]["status"], "fail")


class PresetTagStrippingTests(unittest.TestCase):
    """Preset captions carry ASS override tags + \\N breaks (Modern
    Documentary highlights, e.g. {\\c&H00CCFF&}BRONZE{\\c&H00FFFFFF&}).
    QA word extraction must see the plain words, not the formatting:
    before this fix a tagged caption file failed captions_cover_script
    ('{\\c&H00CCFF&}BRONZE...' does not match 'bronze') and
    captions_timing (29/151 words unmapped on the real 60 s render)."""

    TAGGED_EVENTS = [
        (0.0, 2.12, "A GEARED {\\c&H00CCFF&}BRONZE{\\c&H00FFFFFF&}\\NMACHINE"),
        (2.12, 4.0, "THAT PREDICTED {\\c&H00CCFF&}ECLIPSES{\\c&H00FFFFFF&}"),
    ]
    SCRIPT = ["A", "geared", "bronze", "machine", "that", "predicted",
              "eclipses"]
    TIMINGS = [(0.0, 0.4, "A"), (0.4, 0.9, "geared"),
               (0.9, 1.5, "bronze"), (1.5, 2.12, "machine"),
               (2.12, 2.6, "that"), (2.6, 3.3, "predicted"),
               (3.3, 4.0, "eclipses")]

    def test_strip_ass_tags_removes_overrides_and_breaks(self):
        from src.caption_validation import strip_ass_tags
        self.assertEqual(
            strip_ass_tags("A GEARED {\\c&H00CCFF&}BRONZE{\\c&H00FFFFFF&}\\NMACHINE"),
            "A GEARED BRONZE MACHINE")
        self.assertEqual(strip_ass_tags("{\\b1}BOLD{\\b0} plain"), "BOLD plain")

    def test_tagged_events_pass_cover_script(self):
        passed, detail = check_cover_script(self.TAGGED_EVENTS, self.SCRIPT)
        self.assertTrue(passed, detail)

    def test_tagged_events_pass_timing(self):
        passed, detail, verified = check_timing(
            self.TAGGED_EVENTS, self.SCRIPT, self.TIMINGS, duration=4.0)
        self.assertTrue(passed, detail)
        self.assertTrue(verified)

    def test_tagged_ass_file_parses_and_passes(self):
        # Same content as a real preset .ass file on disk.
        ass_text = (
            "[Script Info]\nTitle: t\n\n[V4+ Styles]\nFormat: Name, Fontname\n"
            "Style: Modern Documentary,Montserrat ExtraBold,60\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:00.00,0:00:02.12,Modern Documentary,,0,0,0,,"
            "A GEARED {\\c&H00CCFF&}BRONZE{\\c&H00FFFFFF&}\\NMACHINE\n"
            "Dialogue: 0,0:00:02.12,0:00:04.00,Modern Documentary,,0,0,0,,"
            "THAT PREDICTED {\\c&H00CCFF&}ECLIPSES{\\c&H00FFFFFF&}\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tagged.ass")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(ass_text)
            events = parse_ass(path)
            passed, detail = check_cover_script(events, self.SCRIPT)
            self.assertTrue(passed, detail)


if __name__ == "__main__":
    unittest.main()
