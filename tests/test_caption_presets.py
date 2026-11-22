"""Tests for the Deep Scan caption preset system (src/caption_presets.py).

Additive only: nothing here touches the existing pipeline or QA checks.
Word timings used in tests are the real first-15s timings from the
Antikythera Short narration (faster-whisper, small model).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.caption_presets import (  # noqa: E402
    DOCUMENTARY,
    MINIMAL,
    PRESETS,
    VIRAL,
    build_ass,
    fit_size,
    measure_width,
    resolve_font,
    segment_words,
    validate_preset,
)

WORDS_0_15 = [
    {"word": "A", "start": 0.00, "end": 0.40},
    {"word": "geared", "start": 0.40, "end": 0.66},
    {"word": "bronze", "start": 0.66, "end": 0.98},
    {"word": "machine", "start": 0.98, "end": 1.52},
    {"word": "that", "start": 1.52, "end": 1.70},
    {"word": "predicted", "start": 1.70, "end": 2.12},
    {"word": "eclipses", "start": 2.12, "end": 2.86},
    {"word": "existed", "start": 2.86, "end": 3.36},
    {"word": "in", "start": 3.36, "end": 3.74},
    {"word": "the", "start": 3.74, "end": 3.84},
    {"word": "ancient", "start": 3.84, "end": 4.10},
    {"word": "world", "start": 4.10, "end": 4.50},
    {"word": "about", "start": 4.50, "end": 4.76},
    {"word": "two", "start": 4.76, "end": 5.12},
    {"word": "thousand", "start": 5.12, "end": 5.52},
    {"word": "years", "start": 5.52, "end": 5.78},
    {"word": "ago.", "start": 5.78, "end": 6.16},
    {"word": "Sponge", "start": 6.60, "end": 6.94},
    {"word": "divers", "start": 6.94, "end": 7.46},
    {"word": "found", "start": 7.46, "end": 7.98},
    {"word": "the", "start": 7.98, "end": 8.14},
    {"word": "wreck", "start": 8.14, "end": 8.34},
    {"word": "off", "start": 8.34, "end": 8.56},
    {"word": "Antikythera", "start": 8.56, "end": 9.36},
    {"word": "in", "start": 9.36, "end": 9.48},
    {"word": "1900,", "start": 9.48, "end": 10.22},
    {"word": "recovered", "start": 10.64, "end": 11.24},
    {"word": "the", "start": 11.24, "end": 11.46},
    {"word": "corroded", "start": 11.46, "end": 11.88},
    {"word": "lump", "start": 11.88, "end": 12.12},
    {"word": "in", "start": 12.12, "end": 12.32},
    {"word": "1901", "start": 12.32, "end": 13.08},
    {"word": "and", "start": 13.08, "end": 13.82},
    {"word": "its", "start": 13.82, "end": 13.98},
    {"word": "fragments", "start": 13.98, "end": 14.36},
    {"word": "are", "start": 14.36, "end": 14.64},
    {"word": "now", "start": 14.64, "end": 14.78},
    {"word": "held", "start": 14.78, "end": 15.04},
]

PROD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "productions", "antikythera-short-2026-11-15",
)
# Caption-free 15s base (rebuilt from the production's own visual recipe;
# the finished MP4 has the production captions burned in, so the render
# test burns onto the base instead of doubling the text).
SRC_MP4 = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "productions", "caption-preset-previews", "base_15s_nocaptions.mp4",
)
FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "fonts",
)


def _parse_ass(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    events = []
    for line in text.splitlines():
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            events.append({
                "start": parts[1], "end": parts[2],
                "style": parts[3], "text": parts[9],
            })
    return text, events


def _to_seconds(ts):
    h, m, rest = ts.split(":")
    s, cs = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100.0


class TestPresetDefinitions(unittest.TestCase):
    def test_all_presets_valid(self):
        self.assertEqual(set(PRESETS), {"documentary", "viral", "minimal"})
        for slug, preset in PRESETS.items():
            self.assertEqual(validate_preset(preset), [], f"{slug}: "
                             f"{validate_preset(preset)}")

    def test_presets_are_distinct(self):
        sigs = {(p.font_size, p.animation, p.highlight_mode, p.case)
                for p in PRESETS.values()}
        self.assertEqual(len(sigs), 3, "presets must differ from each other")

    def test_bundled_fonts_exist_and_load(self):
        from PIL import ImageFont

        for preset in PRESETS.values():
            name, path, bundled = resolve_font(preset)
            self.assertTrue(bundled, f"{preset.slug} should use bundled font")
            self.assertTrue(os.path.isfile(path), path)
            font = ImageFont.truetype(path, preset.font_size)
            self.assertGreater(font.getlength("Antikythera"), 0)

    def test_fontconfig_resolves_ass_fontname(self):
        # The CI runner does not have Montserrat installed system-wide
        # (run #260: fc-match fell back to DejaVu Sans), so scope
        # fontconfig to the bundled fonts with a throwaway config file
        # instead of depending on the host's installed fonts.
        # FONTCONFIG_FILE replaces the default config entirely, so only
        # assets/fonts is scanned; fc-cache builds the cache for it.
        if shutil.which("fc-match") is None:
            self.skipTest("fc-match not available")
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, "fc-cache")
            os.makedirs(cache_dir, exist_ok=True)
            conf_path = os.path.join(tmp, "fonts.conf")
            with open(conf_path, "w", encoding="utf-8") as fh:
                fh.write(
                    '<?xml version="1.0"?>\n'
                    '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
                    "<fontconfig>\n"
                    f"  <dir>{FONT_DIR}</dir>\n"
                    f"  <cachedir>{cache_dir}</cachedir>\n"
                    "</fontconfig>\n")
            env = dict(os.environ, FONTCONFIG_FILE=conf_path)
            if shutil.which("fc-cache") is not None:
                subprocess.run(["fc-cache", "-f"], env=env,
                               capture_output=True, timeout=60)
            for preset in PRESETS.values():
                out = subprocess.run(
                    ["fc-match", preset.font_name],
                    capture_output=True, text=True, timeout=30, env=env,
                ).stdout
                self.assertIn("Montserrat", out,
                              f"{preset.slug}: fc-match {preset.font_name!r} "
                              f"-> {out!r}")

    def test_no_stopword_highlighted(self):
        for preset in PRESETS.values():
            for word in preset.highlight_words:
                self.assertNotIn(word, {
                    "a", "an", "the", "in", "on", "of", "to", "and", "or",
                    "for", "what", "that", "it", "is", "are", "was", "were",
                    "its", "no", "about", "again", "until", "off", "now",
                    "held", "at", "made", "who", "paid", "have", "we",
                    "do", "you", "think", "does", "record", "actually",
                    "support", "happened", "remains",
                })


class TestSegmentation(unittest.TestCase):
    def test_events_cover_all_words_in_order(self):
        for preset in PRESETS.values():
            events = segment_words(WORDS_0_15, preset)
            flat = [w["word"] for ev in events for w in ev]
            self.assertEqual(flat, [w["word"] for w in WORDS_0_15])

    def test_events_break_at_sentence_boundaries(self):
        events = segment_words(WORDS_0_15, DOCUMENTARY)
        # First sentence ("...years ago.") must not be split mid-sentence
        # across an event that also contains the next sentence.
        joined = [" ".join(w["word"] for w in ev) for ev in events]
        self.assertTrue(any("ago." in j for j in joined))
        for j in joined:
            if "ago." in j:
                self.assertTrue(j.rstrip().endswith("ago."),
                                f"event continues past sentence end: {j!r}")
                break

    def test_events_respect_max_words(self):
        for preset in PRESETS.values():
            for ev in segment_words(WORDS_0_15, preset):
                self.assertLessEqual(len(ev), preset.max_words_per_event)

    def test_no_orphan_line(self):
        # A comma at the start of an event must not strand one word on
        # its own line (seen: "1900," alone above "recovered the ...").
        from src.caption_presets import _split_line_words

        for preset in PRESETS.values():
            for ev in segment_words(WORDS_0_15, preset):
                if len(ev) >= 4:
                    for ln in _split_line_words(ev, preset):
                        self.assertGreaterEqual(
                            len(ln), 2,
                            f"{preset.slug}: orphan line in {ev}")

    def test_event_times_monotonic_and_within_clip(self):
        for preset in PRESETS.values():
            events = segment_words(WORDS_0_15, preset)
            prev_end = 0.0
            for ev in events:
                self.assertLessEqual(prev_end, ev[0]["start"] + 0.01)
                self.assertLess(ev[0]["start"], ev[-1]["end"])
                prev_end = ev[-1]["end"]
        # build_ass with a duration clamps the last event to the clip.
        import tempfile

        tmp = tempfile.mkdtemp(prefix="caption_clamp_")
        try:
            for preset in PRESETS.values():
                path = os.path.join(tmp, f"clamp-{preset.slug}.ass")
                build_ass(preset, WORDS_0_15, path, duration=15.0)
                _text, events = _parse_ass(path)
                for ev in events:
                    self.assertLessEqual(_to_seconds(ev["end"]), 15.0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestAssOutput(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "_tmp_caption_test")
        os.makedirs(self.tmp, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_max_two_lines_per_event(self):
        for slug, preset in PRESETS.items():
            path = os.path.join(self.tmp, f"{slug}.ass")
            build_ass(preset, WORDS_0_15, path)
            _text, events = _parse_ass(path)
            self.assertGreater(len(events), 0, slug)
            for ev in events:
                self.assertLessEqual(ev["text"].count("\\N"), 1,
                                     f"{slug}: >2 lines in {ev['text']!r}")

    def test_lines_fit_safe_width(self):
        for slug, preset in PRESETS.items():
            path = os.path.join(self.tmp, f"{slug}.ass")
            build_ass(preset, WORDS_0_15, path)
            _text, events = _parse_ass(path)
            style_size = int(re.search(
                r"Style: [^,]+,[^,]+,(\d+),", _text).group(1))
            _name, font_path, _b = resolve_font(preset)
            max_w = 1080 - preset.margin_l - preset.margin_r
            for ev in events:
                plain = re.sub(r"\{[^}]*\}", "", ev["text"])
                for line in plain.split("\\N"):
                    w = measure_width(line, font_path, style_size)
                    self.assertLessEqual(
                        w, max_w * 1.05,
                        f"{slug}: line too wide ({w:.0f}px > {max_w}px): {line!r}")

    def test_captions_match_spoken_words(self):
        for slug, preset in PRESETS.items():
            path = os.path.join(self.tmp, f"{slug}.ass")
            build_ass(preset, WORDS_0_15, path)
            _text, events = _parse_ass(path)
            # Karaoke presets emit one event per word, all showing the
            # same segment text — collapse consecutive identical event
            # texts so the comparison sees each segment once.
            plain_events = []
            for ev in events:
                plain = re.sub(r"\{[^}]*\}", "", ev["text"])
                if not plain_events or plain_events[-1] != plain:
                    plain_events.append(plain)
            shown = []
            for plain in plain_events:
                shown.extend(plain.replace("\\N", " ").split())
            spoken = [w["word"].strip(".,") for w in WORDS_0_15]
            shown_norm = [w.strip(".,").lower() for w in shown]
            # Case differs by preset (upper vs sentence); compare lowered.
            self.assertEqual(
                shown_norm, [w.lower() for w in spoken],
                f"{slug}: captions do not match spoken words")

    def test_karaoke_only_in_viral(self):
        # Karaoke is implemented as one event per word (the ASS \k tag
        # does not render in this environment's libass — verified with
        # a minimal test), so no preset file may contain \k at all.
        from src.caption_presets import segment_words

        for slug, preset in PRESETS.items():
            path = os.path.join(self.tmp, f"{slug}.ass")
            build_ass(preset, WORDS_0_15, path)
            text, events = _parse_ass(path)
            self.assertNotIn("\\k", text, f"{slug} must not use \\k tags")
            segments = segment_words(WORDS_0_15, preset)
            if preset.animation == "karaoke":
                # One event per word, tiling the segments.
                self.assertEqual(len(events), len(WORDS_0_15), slug)
            else:
                self.assertEqual(len(events), len(segments), slug)

    def test_karaoke_word_events_tile_segments(self):
        # Each viral event covers exactly one spoken word's time window,
        # and that word is the one highlighted in the event.
        from src.caption_presets import segment_words

        path = os.path.join(self.tmp, "viral.ass")
        build_ass(VIRAL, WORDS_0_15, path)
        _text, events = _parse_ass(path)
        segments = segment_words(WORDS_0_15, VIRAL)
        idx = 0
        for seg in segments:
            seg_events = events[idx:idx + len(seg)]
            self.assertEqual(len(seg_events), len(seg))
            prev_end = _to_seconds(seg_events[0]["start"])
            self.assertAlmostEqual(prev_end, seg[0]["start"], delta=0.01)
            for ev, w in zip(seg_events, seg):
                self.assertAlmostEqual(
                    _to_seconds(ev["start"]), w["start"], delta=0.01)
                self.assertAlmostEqual(
                    _to_seconds(ev["end"]), w["end"], delta=0.01)
                self.assertLessEqual(
                    prev_end, _to_seconds(ev["start"]) + 0.01)
                prev_end = _to_seconds(ev["end"])
                shown = w["word"].upper()
                self.assertIn(
                    "{\\c&H00CCFF&}" + shown + "{\\c&H00FFFFFF&}",
                    ev["text"], f"word {shown!r} not highlighted")
            self.assertAlmostEqual(prev_end, seg[-1]["end"], delta=0.01)
            idx += len(seg)
        self.assertEqual(idx, len(events))

    def test_fade_only_in_minimal(self):
        for slug, preset in PRESETS.items():
            path = os.path.join(self.tmp, f"{slug}.ass")
            build_ass(preset, WORDS_0_15, path)
            text, _ev = _parse_ass(path)
            if preset.animation == "fade":
                self.assertIn("\\fad(", text, slug)
            else:
                self.assertNotIn("\\fad(", text, f"{slug} should not fade")

    def test_ass_header_well_formed(self):
        for slug, preset in PRESETS.items():
            path = os.path.join(self.tmp, f"{slug}.ass")
            build_ass(preset, WORDS_0_15, path)
            text, _ev = _parse_ass(path)
            self.assertIn("ScriptType: v4.00+", text)
            self.assertIn("PlayResX: 1080", text)
            self.assertIn("PlayResY: 1920", text)
            self.assertIn("Format: Name, Fontname, Fontsize,", text)
            # No raw braces leak into visible text (they would break ASS).
            for ev in _parse_ass(path)[1]:
                visible = re.sub(r"\{\\[^}]*\}", "", ev["text"])
                self.assertNotIn("{", visible)
                self.assertNotIn("}", visible)

    def test_render_each_preset(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg not available")
        if not os.path.isfile(SRC_MP4):
            self.skipTest("production MP4 not present")
        for slug, preset in PRESETS.items():
            ass = os.path.join(self.tmp, f"{slug}.ass")
            build_ass(preset, WORDS_0_15, ass)
            out = os.path.join(self.tmp, f"{slug}.mp4")
            r = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", "0", "-i", SRC_MP4,
                 "-t", "3", "-vf", f"ass={ass}:fontsdir={FONT_DIR}",
                 "-c:a", "copy", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 out],
                capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(r.returncode, 0, f"{slug}: {r.stderr[-400:]}")
            self.assertTrue(os.path.isfile(out))
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=width,height,r_frame_rate",
                 "-show_entries", "format=duration", "-of", "csv", out],
                capture_output=True, text=True, timeout=60,
            ).stdout
            self.assertIn("1080,1920", probe.replace(" ", ""))
            self.assertIn("30/1", probe)


if __name__ == "__main__":
    unittest.main()
