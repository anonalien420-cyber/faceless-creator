"""Tests for the Deep Scan pronunciation dictionary (src/pronunciation.py).

The dictionary maps written forms to Kokoro TTS input (kokoro_text).
Rules under test:
- Only verified entries with a non-null kokoro_text are applied.
- Unknown entries are never respelled, only flagged.
- Matching is longest-form-first and word-boundary aware.
- Ordinary words and the written script are never changed.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.pronunciation import (  # noqa: E402
    apply_pronunciation,
    flag_unknown,
    load_dictionary,
    verified_entries,
)

DICT_PATH = os.path.join(os.path.dirname(__file__), "..",
                         "data", "pronunciation_dictionary.json")

# Small in-memory dictionary for behaviour tests (does not depend on
# the real file's contents).
FAKE = {
    "entries": [
        {"name": "Stais", "aliases": [], "status": "verified",
         "kokoro_text": "Stah ees", "ipa": "/ˈsta.is/"},
        {"name": "Taposiris Magna", "aliases": [], "status": "verified",
         "kokoro_text": "tap-oh-SEE-riss MAG-nah", "ipa": None},
        {"name": "Exeligmos", "aliases": [], "status": "unknown — flag for review",
         "kokoro_text": None, "ipa": None},
        {"name": "Antikythera", "aliases": [], "status": "verified",
         "kokoro_text": None, "ipa": "/ˌæntɪkɪˈθɪərə/"},
    ]
}


class TestLoadDictionary(unittest.TestCase):
    def test_real_file_loads(self):
        data = load_dictionary(DICT_PATH)
        self.assertIn("entries", data)
        self.assertTrue(len(data["entries"]) >= 10)

    def test_real_file_has_stais_verified(self):
        data = load_dictionary(DICT_PATH)
        by_name = {e["name"]: e for e in data["entries"]}
        self.assertIn("Stais", by_name)
        self.assertEqual(by_name["Stais"]["status"], "verified")
        self.assertTrue(by_name["Stais"]["kokoro_text"])

    def test_real_file_unknowns_have_no_respelling(self):
        data = load_dictionary(DICT_PATH)
        for entry in data["entries"]:
            if entry["status"] != "verified":
                self.assertIsNone(entry.get("kokoro_text"),
                                  f"{entry['name']} is unknown but has a respelling")
                self.assertIsNone(entry.get("ipa"),
                                  f"{entry['name']} is unknown but has an IPA")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_dictionary("/nonexistent/pronunciation_dictionary.json")


class TestVerifiedEntries(unittest.TestCase):
    def test_only_verified_with_kokoro_text(self):
        names = {e["name"] for e in verified_entries(FAKE)}
        self.assertEqual(names, {"Stais", "Taposiris Magna"})
        # Antikythera is verified but needs no respelling (Kokoro already
        # renders it correctly), so it is not an applicable entry.
        self.assertNotIn("Antikythera", names)


class TestApplyPronunciation(unittest.TestCase):
    def test_applies_verified_respelling(self):
        text, applied = apply_pronunciation(
            "and the museum's Valerios Stais studied it.", FAKE)
        self.assertEqual(text, "and the museum's Valerios Stah ees studied it.")
        self.assertEqual(applied, ["Stais"])

    def test_case_insensitive_match(self):
        text, applied = apply_pronunciation("STAIS was Greek.", FAKE)
        self.assertIn("Stah ees", text)
        self.assertEqual(applied, ["Stais"])

    def test_possessive_still_matches(self):
        text, _ = apply_pronunciation("the Stais's gear.", FAKE)
        self.assertTrue(text.startswith("the Stah ees's gear."))

    def test_unknown_never_applied(self):
        text, applied = apply_pronunciation(
            "the Exeligmos dial turns slowly.", FAKE)
        self.assertEqual(text, "the Exeligmos dial turns slowly.")
        self.assertEqual(applied, [])

    def test_no_respelling_entry_unchanged(self):
        text, applied = apply_pronunciation(
            "found off Antikythera in 1900.", FAKE)
        self.assertEqual(text, "found off Antikythera in 1900.")
        self.assertEqual(applied, [])

    def test_multiword_beats_single_word(self):
        text, applied = apply_pronunciation(
            "the tunnel under Taposiris Magna.", FAKE)
        self.assertEqual(text, "the tunnel under tap-oh-SEE-riss MAG-nah.")
        self.assertEqual(applied, ["Taposiris Magna"])

    def test_ordinary_words_untouched(self):
        script = ("A geared bronze machine that predicted eclipses existed "
                  "in the ancient world about two thousand years ago.")
        text, applied = apply_pronunciation(script, FAKE)
        self.assertEqual(text, script)
        self.assertEqual(applied, [])

    def test_real_dictionary_applies_stais(self):
        data = load_dictionary(DICT_PATH)
        text, applied = apply_pronunciation(
            "and the museum's Valerios Stais studied it.", data)
        self.assertNotIn("Stais", text)
        self.assertIn("Stais", applied)
        # The respelling must be two syllables, not the one-syllable
        # "styes" sound Kokoro produced for the bare spelling.
        self.assertIn(" ", apply_pronunciation(
            "Stais", data)[0].strip())


class TestFlagUnknown(unittest.TestCase):
    def test_flags_unknown_entries(self):
        flagged = flag_unknown("the Exeligmos dial and the Saros dial.", FAKE)
        self.assertEqual(flagged, ["Exeligmos"])

    def test_does_not_flag_verified(self):
        flagged = flag_unknown("off Antikythera in 1900.", FAKE)
        self.assertEqual(flagged, [])

    def test_real_dictionary_flags_exeligmos(self):
        data = load_dictionary(DICT_PATH)
        flagged = flag_unknown(
            "the back dials show the Metonic, Saros and Exeligmos cycles.",
            data)
        self.assertIn("Exeligmos", flagged)
        self.assertNotIn("Metonic", flagged)
        self.assertNotIn("Saros", flagged)


if __name__ == "__main__":
    unittest.main()
