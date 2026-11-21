"""Tests for wiring the Modern Documentary caption preset into make_ass
(Phase 2, F5): production captions must use the bundled Montserrat
ExtraBold, UPPERCASE, max 2 lines, and the preset's own segmentation
rules — sentence segmentation with up to 6 words/event. That last
point is a DELIBERATE deviation from the legacy kinetic <=3-words
rule: the preset is the authority, so an event may hold 4-6 words.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.caption_presets import DOCUMENTARY, resolve_font  # noqa: E402
from src.video import build_video, make_ass  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

SCRIPT = ("A geared bronze machine that predicted eclipses. "
          "Sponge divers found the wreck.")
WORDS = ["A", "geared", "bronze", "machine", "that", "predicted",
         "eclipses.", "Sponge", "divers", "found", "the", "wreck."]
TIMED = [(i * 0.5, (i + 1) * 0.5, w) for i, w in enumerate(WORDS)]


def _parse_ass(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    events = []
    for line in text.splitlines():
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            events.append({"start": parts[1], "end": parts[2],
                           "style": parts[3], "text": parts[9]})
    return text, events


def _plain(text):
    return re.sub(r"\{[^}]*\}", "", text)


def _write_narration_audio(path, seconds=3.0):
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}", "-c:a", "aac",
         "-b:a", "128k", path], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")


class DocumentaryPresetAssTests(unittest.TestCase):
    def test_preset_emits_montserrat_extrabold(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "caps.ass")
            make_ass(SCRIPT, 6.0, path, word_timings=TIMED,
                     preset="documentary")
            text, _events = _parse_ass(path)
        self.assertIn("Montserrat ExtraBold", text)
        name, font_path, bundled = resolve_font(DOCUMENTARY)
        self.assertTrue(bundled, "production preset must use bundled font")
        self.assertEqual(name, "Montserrat ExtraBold")
        self.assertTrue(os.path.isfile(font_path))

    def test_preset_captions_uppercase_max_two_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "caps.ass")
            make_ass(SCRIPT, 6.0, path, word_timings=TIMED,
                     preset="documentary")
            _text, events = _parse_ass(path)
        self.assertGreater(len(events), 0)
        for ev in events:
            plain = _plain(ev["text"])
            self.assertEqual(plain, plain.upper(),
                             f"not UPPERCASE: {plain!r}")
            self.assertLessEqual(plain.count("\\N"), 1,
                                 f">2 lines in {plain!r}")

    def test_preset_segmentation_is_the_authority(self):
        # Sentence 1 has 7 words -> chunked 4+3 (max 6/event); sentence
        # 2 has 5 words -> 1 event. Total 3 events, one holding 4 words
        # — MORE than the legacy kinetic <=3 rule. Pinned deliberately:
        # the preset's rule wins over the legacy rule.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "caps.ass")
            make_ass(SCRIPT, 6.0, path, word_timings=TIMED,
                     preset="documentary")
            _text, events = _parse_ass(path)
        self.assertEqual(len(events), 3)
        counts = [len(_plain(ev["text"]).replace("\\N", " ").split())
                  for ev in events]
        self.assertEqual(sorted(counts), [3, 4, 5])
        self.assertLessEqual(max(counts), DOCUMENTARY.max_words_per_event)
        self.assertGreater(max(counts), 3,
                           "preset allows >3 words/event; if this fails "
                           "the legacy rule has crept back in")
        # No event crosses the sentence boundary.
        joined = [" ".join(_plain(ev["text"]).replace("\\N", " ").split())
                  for ev in events]
        for j in joined:
            if "ECLIPSES." in j:
                self.assertTrue(j.rstrip().endswith("ECLIPSES."),
                                f"event continues past sentence end: {j!r}")
                break

    def test_preset_uses_preset_margins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "caps.ass")
            make_ass(SCRIPT, 6.0, path, word_timings=TIMED,
                     preset="documentary")
            text, _events = _parse_ass(path)
        # Style line ends ...,MarginL=60,MarginR=60,MarginV=400,Encoding=1
        self.assertRegex(text, r",60,60,400,1\n")

    def test_preset_without_timings_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                make_ass(SCRIPT, 6.0, os.path.join(tmp, "caps.ass"),
                         preset="documentary")

    def test_preset_object_accepted_as_well_as_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "caps.ass")
            make_ass(SCRIPT, 6.0, path, word_timings=TIMED,
                     preset=DOCUMENTARY)
            text, _events = _parse_ass(path)
        self.assertIn("Montserrat ExtraBold", text)

    def test_extra_captions_append_in_preset_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "caps.ass")
            make_ass(SCRIPT, 6.0, path, word_timings=TIMED,
                     preset="documentary",
                     extra_captions=[(0.0, 1.0, "LIKE AND SUBSCRIBE")])
            _text, events = _parse_ass(path)
        self.assertEqual(events[-1]["style"], "Modern Documentary")
        self.assertTrue(events[-1]["text"].endswith("LIKE AND SUBSCRIBE"))

    def test_legacy_path_unchanged_when_no_preset(self):
        # No preset + timings still gives the legacy kinetic <=3-word
        # frames (12 words -> 4 events), DejaVu Sans.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "caps.ass")
            make_ass(SCRIPT, 6.0, path, word_timings=TIMED)
            text, events = _parse_ass(path)
        self.assertEqual(len(events), 4)
        self.assertIn("DejaVu Sans", text)
        self.assertNotIn("Montserrat", text)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg and ffprobe are required")
class DocumentaryPresetRenderTests(unittest.TestCase):
    def test_build_video_preset_renders_and_requires_timings(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "narr.m4a")
            _write_narration_audio(audio, seconds=3.0)
            script = {"text": SCRIPT, "topic": "Test Topic",
                      "hook": "A geared bronze machine."}
            # No timings + preset -> loud refusal, no render.
            with self.assertRaises(ValueError):
                build_video(script, audio, os.path.join(tmp, "x.mp4"),
                            visuals=None, duration=3.0,
                            caption_preset="documentary",
                            normalize_loudness=False)
            # No timings + require flag -> loud refusal too.
            with self.assertRaises(ValueError):
                build_video(script, audio, os.path.join(tmp, "y.mp4"),
                            visuals=None, duration=3.0,
                            require_word_timings=True,
                            normalize_loudness=False)
            out = os.path.join(tmp, "out.mp4")
            build_video(script, audio, out, visuals=None, duration=3.0,
                        word_timings=TIMED, caption_preset="documentary",
                        require_word_timings=True,
                        normalize_loudness=False)
            self.assertTrue(os.path.isfile(out))
            ass = out + ".ass"
            self.assertTrue(os.path.isfile(ass))
            with open(ass, encoding="utf-8") as fh:
                self.assertIn("Montserrat ExtraBold", fh.read())
            manifest = out + ".visuals.json"
            self.assertTrue(os.path.isfile(manifest),
                            "build_video must write the visuals manifest")
            with open(manifest, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(set(data), {"duration", "chunks",
                                        "real_seconds", "gradient_seconds"})
            self.assertEqual(data["gradient_seconds"], 3.0)
            self.assertEqual(data["real_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
