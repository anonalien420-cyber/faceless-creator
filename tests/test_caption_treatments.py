"""Tests for src/caption_treatments.py (caption treatments + hook/fact/
narration ASS generation). Uses the real Antikythera narration timings
(faster-whisper output stored as a fixture — see
tests/fixtures/antikythera-words.json) and the real evidence ledger, so
the assertions run against production-shaped data without re-running
transcription in the test suite.

Real 3s renders: each treatment's ASS is burned onto a 3s 1080x1920
clip with ffmpeg/libass (fontsdir=assets/fonts) and the output is
verified to exist with ~3s duration. That is the parseability check —
libass rejects a malformed ASS file at filter load.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.caption_treatments import (  # noqa: E402
    HOOK,
    FACT,
    NARRATION,
    PRESETS_FALLBACK_USED,
    TREATMENTS,
    align_script_to_timings,
    allowed_keywords,
    build_fact_ass,
    build_hook_ass,
    build_narration_ass,
    build_treatment_ass,
    estimate_word_timings,
    get_treatment,
    get_word_timings,
    parse_ass_dialogues,
    validate_ass_file,
    validate_treatment,
)

BRANCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_fixture():
    script = open(os.path.join(
        BRANCH, "productions", "antikythera-short-2026-11-15",
        "narration.txt"), encoding="utf-8").read().strip()
    ledger = json.load(open(os.path.join(BRANCH, "data",
                                         "evidence_ledger.json"),
                            encoding="utf-8"))
    raw = json.load(open(os.path.join(BRANCH, "tests", "fixtures",
                                      "antikythera-words.json"),
                         encoding="utf-8"))
    return script, ledger, align_script_to_timings(script, raw)


SCRIPT, LEDGER, WORDS = _load_fixture()
ALLOWED = allowed_keywords(LEDGER)


def _render_3s_clip(ass_path, out_path):
    """Burn ``ass_path`` onto a 3s 1080x1920 clip; return (returncode, stderr)."""
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=3",
        "-vf", f"ass={ass_path}:fontsdir={os.path.join(BRANCH, 'assets', 'fonts')}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "3", out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stderr


def _probe_duration(path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(proc.stdout.strip())


class TreatmentDefinitionTests(unittest.TestCase):
    def test_three_treatments_exist_and_differ(self):
        self.assertEqual(set(TREATMENTS), {"hook", "fact", "narration"})
        # Largest type for the hook, calmest for ordinary narration.
        self.assertGreater(HOOK.font_size, FACT.font_size)
        self.assertGreater(FACT.font_size, NARRATION.font_size)
        self.assertEqual(HOOK.font_size, 96)
        self.assertEqual(FACT.font_size, 72)
        self.assertEqual(NARRATION.font_size, 64)

    def test_hook_is_karaoke_with_scale_only_on_highlights(self):
        self.assertEqual(HOOK.animation, "karaoke")
        self.assertEqual(HOOK.highlight_mode, "karaoke")
        self.assertAlmostEqual(HOOK.scale_emphasis, 1.15)
        self.assertEqual(HOOK.max_words_per_event, 4)  # 1-4 word groups

    def test_fact_has_subtle_scale_no_karaoke(self):
        self.assertEqual(FACT.animation, "none")
        self.assertAlmostEqual(FACT.scale_emphasis, 1.12)
        self.assertEqual(FACT.max_words_per_event, 6)

    def test_narration_is_calm_no_karaoke_no_scale(self):
        self.assertEqual(NARRATION.animation, "fade")
        self.assertAlmostEqual(NARRATION.scale_emphasis, 1.0)
        self.assertEqual(NARRATION.max_words_per_event, 4)

    def test_validate_treatments_clean(self):
        for slug in TREATMENTS:
            self.assertEqual(validate_treatment(slug), [],
                             f"treatment {slug} has problems")

    def test_get_treatment_rejects_unknown_slug(self):
        with self.assertRaises(ValueError):
            get_treatment("bounce-everything")

    def test_presets_module_is_used_not_fallback(self):
        # In the repo the real caption_presets module must load; the
        # built-in fallback exists only for out-of-repo copies.
        self.assertFalse(PRESETS_FALLBACK_USED)


class AlignmentTests(unittest.TestCase):
    def test_alignment_preserves_script_words(self):
        script_words = SCRIPT.split()
        self.assertEqual(len(WORDS), len(script_words))
        self.assertEqual([w["word"] for w in WORDS], script_words)

    def test_alignment_timings_are_monotone_and_cover_narration(self):
        self.assertEqual(WORDS[0]["start"], 0.0)
        last_end = 0.0
        for w in WORDS:
            self.assertGreaterEqual(w["start"], last_end - 0.01)
            self.assertGreater(w["end"], w["start"])
            last_end = w["end"]
        self.assertAlmostEqual(last_end, 62.36, delta=0.5)

    def test_estimate_timings_is_deterministic_fallback(self):
        a = estimate_word_timings(SCRIPT, 63.0)
        b = estimate_word_timings(SCRIPT, 63.0)
        self.assertEqual(a, b)
        self.assertEqual(len(a), len(SCRIPT.split()))

    def test_get_word_timings_rejects_missing_audio(self):
        with self.assertRaises(FileNotFoundError):
            get_word_timings("/nonexistent/narration.mp3", SCRIPT)


class HookAssTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "hook.ass")
        build_hook_ass(WORDS, self.path, ledger=LEDGER)

    def tearDown(self):
        self.tmp.cleanup()

    def test_hook_text_appears_by_half_a_second(self):
        dialogues = parse_ass_dialogues(self.path)
        self.assertTrue(dialogues)
        first_start = dialogues[0]["start"]
        h, m, rest = first_start.split(":")
        s, cs = rest.split(".")
        start_s = int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100
        self.assertLessEqual(start_s, 0.5)

    def test_hook_covers_only_first_three_seconds(self):
        dialogues = parse_ass_dialogues(self.path)
        for d in dialogues:
            h, m, rest = d["end"].split(":")
            s, cs = rest.split(".")
            end_s = int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100
            self.assertLessEqual(end_s, 3.1)

    def test_hook_events_are_one_to_four_words(self):
        for d in parse_ass_dialogues(self.path):
            plain = re.sub(r"\{[^}]*\}", "", d["text"]).replace("\\N", " ")
            self.assertLessEqual(len(plain.split()), 4)

    def test_hook_ass_validates_clean(self):
        self.assertEqual(
            validate_ass_file(self.path, allowed=ALLOWED,
                              require_first_by=0.5), [])


class FactAssTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_fact_ass_builds_on_known_claim(self):
        path = os.path.join(self.tmp.name, "fact.ass")
        build_fact_ass(WORDS, path, "antikythera_04", LEDGER)
        self.assertEqual(validate_ass_file(path, allowed=ALLOWED), [])

    def test_fact_ass_refuses_unknown_claim_status(self):
        # antikythera_10 is UNKNOWN: never a fact caption.
        with self.assertRaises(ValueError):
            build_fact_ass(WORDS, os.path.join(self.tmp.name, "f.ass"),
                           "antikythera_10", LEDGER)

    def test_fact_ass_refuses_missing_claim(self):
        with self.assertRaises(ValueError):
            build_fact_ass(WORDS, os.path.join(self.tmp.name, "f.ass"),
                           "antikythera_99", LEDGER)

    def test_fact_highlights_only_claim_keywords(self):
        path = os.path.join(self.tmp.name, "fact.ass")
        build_fact_ass(WORDS, path, "antikythera_04", LEDGER)
        with open(path, encoding="utf-8") as _fh:
            text = _fh.read()
        coloured = re.findall(r"\{\\c[^}]*\}([^{}]+)\{\\c\}", text)
        coloured += re.findall(r"\{\\fs\d+\\c[^}]*\}([^{}]+)\{", text)
        for word in coloured:
            clean = word.strip(".,?!;:").lower()
            self.assertIn(clean, ALLOWED,
                          f"fact caption highlighted {word!r}")


class NarrationAssTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "narr.ass")
        build_narration_ass(WORDS, self.path, ledger=LEDGER)

    def tearDown(self):
        self.tmp.cleanup()

    def test_narration_has_no_karaoke_and_no_word_scale(self):
        with open(self.path, encoding="utf-8") as _fh:
            text = _fh.read()
        self.assertNotIn("\\k", text)
        # No {\fsN\c...} highlight-scale overrides anywhere.
        self.assertEqual(re.findall(r"\{\\fs\d+\\c", text), [])

    def test_narration_ass_validates_clean(self):
        self.assertEqual(validate_ass_file(self.path, allowed=ALLOWED), [])


class AssRulesTests(unittest.TestCase):
    """Rules enforced across every treatment's output."""

    def _build_all(self, tmp):
        paths = {}
        for slug, builder in (
                ("hook", lambda p: build_hook_ass(WORDS, p, ledger=LEDGER)),
                ("fact", lambda p: build_fact_ass(
                    WORDS, p, "antikythera_04", LEDGER)),
                ("narration", lambda p: build_narration_ass(
                    WORDS, p, ledger=LEDGER))):
            path = os.path.join(tmp, f"{slug}.ass")
            builder(path)
            paths[slug] = path
        return paths

    def test_max_two_lines_per_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            for slug, path in self._build_all(tmp).items():
                for d in parse_ass_dialogues(path):
                    self.assertLessEqual(len(d["text"].split("\\N")), 2,
                                         f"{slug} event has >2 lines")

    def test_text_inside_safe_zones(self):
        with tempfile.TemporaryDirectory() as tmp:
            for slug, path in self._build_all(tmp).items():
                self.assertEqual(
                    validate_ass_file(path, allowed=ALLOWED), [],
                    f"{slug} ASS failed safe-zone validation")
                with open(path, encoding="utf-8") as _fh:
                    text = _fh.read()
                style_line = next(
                    ln for ln in text.splitlines() if ln.startswith("Style:"))
                fields = style_line.split(",")
                # Format: Name, Fontname, Fontsize, Primary, Secondary,
                # Outline, Back, Bold, Italic, Underline, StrikeOut,
                # ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,
                # Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
                margin_v = int(fields[21])
                self.assertGreaterEqual(margin_v, 380)
                self.assertLessEqual(margin_v, 576)

    def test_highlighting_only_on_allowed_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            for slug, path in self._build_all(tmp).items():
                with open(path, encoding="utf-8") as _fh:
                    text = _fh.read()
                coloured = re.findall(r"\{\\c[^}]*\}([^{}]+)\{\\c\}", text)
                coloured += re.findall(r"\{\\fs\d+\\c[^}]*\}([^{}]+)\{",
                                       text)
                scaled = re.findall(r"\{\\fs\d+\\c[^}]*\}([^{}]+)\{", text)
                for word in coloured + scaled:
                    clean = word.strip(".,?!;:").lower()
                    self.assertIn(clean, ALLOWED,
                                  f"{slug} highlighted {word!r}")
                # No stopword is ever highlighted.
                for word in coloured:
                    self.assertNotIn(word.strip(".,?!;:").lower(),
                                     {"the", "a", "and", "of", "in"})

    def test_ass_generation_is_deterministic_and_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            t0 = time.time()
            first = self._build_all(tmp)
            first_bytes = {s: open(p, "rb").read()
                           for s, p in first.items()}
            second = self._build_all(tmp)
            elapsed = time.time() - t0
            for slug, path in second.items():
                self.assertEqual(open(path, "rb").read(), first_bytes[slug],
                                 f"{slug} ASS is not deterministic")
            # Three full-length ASS files (63s narration) in well under 10s.
            self.assertLess(elapsed, 10.0,
                            f"ASS generation took {elapsed:.2f}s")


class RenderTests(unittest.TestCase):
    """Real 3s renders: ffmpeg/libass must accept each treatment's ASS."""

    def test_render_three_second_clip_per_treatment(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg not available")
        with tempfile.TemporaryDirectory() as tmp:
            cases = (
                ("hook", lambda p: build_hook_ass(WORDS, p, ledger=LEDGER)),
                ("fact", lambda p: build_fact_ass(
                    WORDS, p, "antikythera_04", LEDGER)),
                ("narration", lambda p: build_narration_ass(
                    WORDS, p, ledger=LEDGER)),
            )
            for slug, builder in cases:
                ass_path = os.path.join(tmp, f"{slug}.ass")
                builder(ass_path)
                out_path = os.path.join(tmp, f"{slug}.mp4")
                rc, stderr = _render_3s_clip(ass_path, out_path)
                self.assertEqual(rc, 0,
                                 f"{slug} ASS failed libass render: {stderr}")
                self.assertTrue(os.path.isfile(out_path))
                self.assertAlmostEqual(_probe_duration(out_path), 3.0,
                                       delta=0.3)


if __name__ == "__main__":
    unittest.main()
