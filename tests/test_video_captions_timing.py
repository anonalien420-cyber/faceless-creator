"""Tests for timed caption alignment (src/video.py).

Subtitles must follow the ACTUAL spoken narration, not a uniform
chunking of the script. `align_script_to_timings` maps each script
word to a (start, end) span from a transcription's word timestamps,
and `make_ass(..., word_timings=...)` builds the kinetic-typography
captions (<=3 words/frame, UPPERCASE) from those spans.

Grounding: the 2026-11-15 Antikythera render's transcription heard
"Valerios Stais studied it" as "valerio's styes studded it" — the
alignment must still give the script words a sensible span (the
replace block shares the timed span evenly) rather than crashing or
dropping the phrase.
"""
import os
import tempfile
import unittest

from src.video import align_script_to_timings, make_ass


class AlignTests(unittest.TestCase):
    def test_exact_match_keeps_word_timings(self):
        script = "sponge divers found the wreck"
        timed = [(0.0, 0.4, "sponge"), (0.4, 0.9, "divers"),
                 (0.9, 1.3, "found"), (1.3, 1.7, "the"),
                 (1.7, 2.2, "wreck")]
        spans = align_script_to_timings(script.split(), timed)
        self.assertEqual(spans, timed)

    def test_number_words_collapse_to_spoken_digits(self):
        # Script says "two thousand years"; Whisper hears "2,000 years".
        script = "two thousand years ago"
        timed = [(4.76, 5.13, "2"), (5.13, 5.50, ",000"),
                 (5.50, 5.90, "years"), (5.90, 6.30, "ago")]
        spans = align_script_to_timings(script.split(), timed)
        self.assertEqual(len(spans), 4)
        # "two" and "thousand" share the "2,000" span evenly.
        self.assertAlmostEqual(spans[0][0], 4.76, places=2)
        self.assertAlmostEqual(spans[0][1], 5.13, places=2)
        self.assertAlmostEqual(spans[1][0], 5.13, places=2)
        self.assertAlmostEqual(spans[1][1], 5.50, places=2)
        self.assertEqual(spans[2], (5.50, 5.90, "years"))

    def test_misheard_phrase_shares_timed_span_evenly(self):
        # The Stais case: script "Valerios Stais studied it", Whisper
        # heard "valerio's styes studded it" over 23.5-25.2s.
        script = "Valerios Stais studied it"
        timed = [(23.50, 23.95, "valerio's"), (23.95, 24.35, "styes"),
                 (24.35, 24.80, "studded"), (24.80, 25.20, "it")]
        spans = align_script_to_timings(script.split(), timed)
        self.assertEqual(len(spans), 4)
        self.assertAlmostEqual(spans[0][0], 23.50, places=2)
        self.assertAlmostEqual(spans[-1][1], 25.20, places=2)
        # Even split of the 1.7s span across the 4 script words.
        for i in range(3):
            self.assertAlmostEqual(spans[i][1], spans[i + 1][0], places=6)
        self.assertEqual([w for _, _, w in spans],
                         ["Valerios", "Stais", "studied", "it"])

    def test_unspoken_script_word_gets_neighbouring_gap(self):
        script = "the museum's Valerios Stais studied it"
        timed = [(22.0, 22.4, "the"), (22.4, 22.9, "museum's"),
                 (23.5, 23.9, "studied"), (23.9, 24.2, "it")]
        spans = align_script_to_timings(script.split(), timed)
        self.assertEqual(len(spans), 6)
        # "Valerios" and "Stais" (unspoken here) sit in the gap
        # between "museum's" (ends 22.9) and "studied" (starts 23.5).
        self.assertGreaterEqual(spans[2][0], 22.9)
        self.assertLessEqual(spans[3][1], 23.5)

    def test_empty_timings_returns_empty(self):
        self.assertEqual(align_script_to_timings("some words".split(), []), [])

    def test_empty_script_returns_empty(self):
        self.assertEqual(align_script_to_timings([], [(0.0, 1.0, "hi")]), [])


class TimedAssTests(unittest.TestCase):
    SCRIPT = "A geared bronze machine that predicted eclipses"
    TIMED = [(0.10, 0.50, "A"), (0.50, 1.00, "geared"),
             (1.00, 1.60, "bronze"), (1.60, 2.10, "machine"),
             (2.10, 2.50, "that"), (2.50, 3.10, "predicted"),
             (3.10, 3.80, "eclipses")]

    def _read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_timed_captions_follow_spoken_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_ass(self.SCRIPT, 3.8,
                            os.path.join(tmp, "caps.ass"),
                            word_timings=self.TIMED)
            lines = [ln for ln in self._read(path).splitlines()
                     if ln.startswith("Dialogue:")]
        # 7 words -> 3 frames of <=3 words each.
        self.assertEqual(len(lines), 3)
        texts = [ln.split("Dialogue: ", 1)[1].split(",", 9)[9] for ln in lines]
        self.assertEqual(texts, ["A GEARED BRONZE", "MACHINE THAT PREDICTED",
                                 "ECLIPSES"])
        # First frame starts 0.03s before "A" is spoken (lead-in), not at 0.
        self.assertTrue(lines[0].startswith("Dialogue: 0,0:00:00.07,"))
        self.assertTrue(lines[-1].endswith(",ECLIPSES"))

    def test_timed_captions_have_no_format_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_ass(self.SCRIPT, 3.8,
                            os.path.join(tmp, "caps.ass"),
                            word_timings=self.TIMED)
            content = self._read(path)
        self.assertIn("Format: Layer, Start, End, Style, Name, MarginL, "
                      "MarginR, MarginV, Effect, Text", content)
        # The ",0,0,0,," defect shows up in the TEXT field (field 10);
        # the same characters legitimately separate the Dialogue fields.
        lines = [ln for ln in content.splitlines()
                 if ln.startswith("Dialogue:")]
        for ln in lines:
            text = ln.split("Dialogue: ", 1)[1].split(",", 9)[9]
            self.assertNotIn(",0,0,0,,", text)

    def test_extra_captions_append_close_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_ass(self.SCRIPT, 3.8,
                            os.path.join(tmp, "caps.ass"),
                            word_timings=self.TIMED,
                            extra_captions=[(0.0, 1.94,
                                             "LIKE AND SUBSCRIBE FOR MORE!")])
            lines = [ln for ln in self._read(path).splitlines()
                     if ln.startswith("Dialogue:")]
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[-1].endswith(",LIKE AND SUBSCRIBE FOR MORE!"))

    def test_legacy_path_unchanged_without_timings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_ass(self.SCRIPT, 3.0, os.path.join(tmp, "caps.ass"))
            lines = [ln for ln in self._read(path).splitlines()
                     if ln.startswith("Dialogue:")]
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            lines[0].split("Dialogue: ", 1)[1].split(",", 9)[9], self.SCRIPT)


if __name__ == "__main__":
    unittest.main()
