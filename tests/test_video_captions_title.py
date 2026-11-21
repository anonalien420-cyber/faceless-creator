"""Regression tests for two render defects found 2026-11-15 on the
first REAL Antikythera Short run (frame-checked at t=2s and t=30s).

1. ASS captions rendered a literal ",0,0,0,," prefix on every line:
   make_ass declared "[Events] Format: Layer, Start, End, Style, Text"
   (5 fields) while its Dialogue lines carry 10 fields, so libass took
   everything after the 4th comma as the Text. The Format line must
   declare all 10 fields so the caption text is only the words.
2. The title card drew the 45-character topic at 72pt, wider than the
   1080px frame, so the title was cut off at both edges for the first
   3 seconds. _fit_fontsize must shrink it to fit the frame width.
"""
import os
import tempfile
import unittest

from src.video import _fit_fontsize, make_ass

LONG_TITLE = "The 2,000-Year-Old Object That Shouldn'T Exist"


class AssFormatTests(unittest.TestCase):
    def test_events_format_declares_all_dialogue_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_ass("A geared bronze machine that predicted eclipses",
                            3.0, os.path.join(tmp, "caps.ass"))
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
        self.assertIn(
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
            "MarginV, Effect, Text", content)

    def test_dialogue_text_field_is_only_the_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_ass("A geared bronze machine that predicted eclipses",
                            3.0, os.path.join(tmp, "caps.ass"))
            with open(path, encoding="utf-8") as fh:
                lines = [ln for ln in fh.read().splitlines()
                         if ln.startswith("Dialogue:")]
        self.assertEqual(len(lines), 1)
        # Split on the first 9 commas: field 10 is the Text.
        text = lines[0].split("Dialogue: ", 1)[1].split(",", 9)[9]
        self.assertEqual(text, "A geared bronze machine that predicted eclipses")
        self.assertNotIn(",0,0,0,,", text)


class TitleFitTests(unittest.TestCase):
    def test_long_title_shrinks_to_fit_frame(self):
        size = _fit_fontsize(LONG_TITLE, 1000, 72)
        self.assertLess(size, 72, "45-char title at 72pt overflows 1080px")
        self.assertGreaterEqual(size, 8)
        try:
            from PIL import ImageFont
        except ImportError:
            self.skipTest("Pillow unavailable; fit is heuristic-only here")
        width = ImageFont.truetype("DejaVuSans-Bold.ttf", size).getlength(LONG_TITLE)
        self.assertLessEqual(width, 1000)

    def test_short_title_keeps_full_size(self):
        self.assertEqual(_fit_fontsize("Short Title", 1000, 72), 72)


if __name__ == "__main__":
    unittest.main()
