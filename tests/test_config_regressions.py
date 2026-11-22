"""Regression tests for the Blocker-3 config/dependency fix (PR #1 branch).

Proves the locked narrator/music/dependency choices cannot silently
revert: requirements.txt must pin kokoro, soundfile, Pillow, numpy and
pyttsx3; config.yaml must name the Kokoro narrator bm_george and the
real mellow-history music bed; src/config.py DEFAULTS must cover every
key config.yaml sets; a missing config file must fail loudly; and an
unknown config key must warn instead of being silently ignored.

Stdlib + unittest only. Run from the repo root:
    python3 -m unittest tests.test_config_regressions -v
"""

import re
import tempfile
import unittest
import warnings
from pathlib import Path

from src.config import DEFAULTS, KNOWN_EXTRA_KEYS, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO_ROOT / "requirements.txt"
CONFIG_YAML = REPO_ROOT / "config.yaml"

# The five dependencies the Blocker-3 fix restores/declares, each pinned.
REQUIRED_PINNED = ("kokoro", "soundfile", "Pillow", "numpy", "pyttsx3")

# The 10 keys config.yaml sets that DEFAULTS used to omit.
FORMERLY_MISSING_KEYS = (
    "channel_timezone",
    "peak_windows",
    "series_name",
    "series_enabled",
    "niche_lock_days",
    "channel_promise",
    "long_videos_per_day",
    "shorts_per_day",
    "long_video_bitrate",
    "reddit_subreddits",
)


def _parse_requirements(text):
    """Return {lowercased name: version} for active (non-comment) lines."""
    pinned = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-]+)==(.+)$", line)
        if match:
            pinned[match.group(1).lower()] = match.group(2).strip()
        else:
            pinned.setdefault("__unpinned__", []).append(line)
    return pinned


def _top_level_keys(text):
    """Top-level `key:` names in the YAML-subset config file."""
    keys = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line or line.startswith("#") or line[:1] in (" ", "\t"):
            continue
        if ":" in line:
            keys.append(line.split(":", 1)[0].strip())
    return keys


class RequirementsTests(unittest.TestCase):
    def test_required_dependencies_present_and_pinned(self):
        pinned = _parse_requirements(REQUIREMENTS.read_text(encoding="utf-8"))
        for name in REQUIRED_PINNED:
            with self.subTest(name=name):
                self.assertIn(name.lower(), pinned,
                              f"{name} missing from requirements.txt")
                self.assertTrue(pinned[name.lower()],
                                f"{name} has an empty pin")

    def test_every_dependency_pinned(self):
        text = REQUIREMENTS.read_text(encoding="utf-8")
        pinned = _parse_requirements(text)
        unpinned = pinned.get("__unpinned__", [])
        self.assertEqual(unpinned, [],
                         f"unpinned requirement lines: {unpinned}")
        # Sanity: the file actually declares dependencies, not just comments.
        self.assertGreaterEqual(len(pinned), len(REQUIRED_PINNED))


class ConfigYamlTests(unittest.TestCase):
    def test_narrator_is_kokoro_bm_george(self):
        config = load_config(str(CONFIG_YAML))
        self.assertEqual(config["narrator_voice"], "bm_george")
        self.assertEqual(config["narrator_tier"], "local")
        self.assertEqual(config["narrator_speed"], 0.9)

    def test_music_library_contains_real_mellow_bed_first(self):
        config = load_config(str(CONFIG_YAML))
        library = config["music_library"]
        self.assertTrue(library, "music_library is empty")
        bed = library[0]
        self.assertEqual(bed["file"], "music/mellow_history_bed.mp3")
        self.assertEqual(bed["genre"], "ambient")
        self.assertEqual(bed["tempo_bpm"], 60)
        self.assertEqual(bed["mood"], "mellow")
        self.assertEqual(bed["license"], "synthesized in-house, royalty-free")
        self.assertIs(bed["example"], False)

    def test_real_config_loads_without_unknown_key_warnings(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            load_config(str(CONFIG_YAML))
        unknown = [str(w.message) for w in caught
                   if issubclass(w.category, UserWarning)
                   and "Unknown config key" in str(w.message)]
        self.assertEqual(unknown, [], f"unexpected warnings: {unknown}")


class DefaultsTests(unittest.TestCase):
    def test_defaults_covers_every_key_config_yaml_sets(self):
        file_keys = _top_level_keys(CONFIG_YAML.read_text(encoding="utf-8"))
        self.assertTrue(file_keys, "no top-level keys found in config.yaml")
        known = set(DEFAULTS) | set(KNOWN_EXTRA_KEYS)
        missing = sorted(set(file_keys) - known)
        self.assertEqual(missing, [],
                         f"keys in config.yaml missing from DEFAULTS: {missing}")

    def test_formerly_missing_keys_present_in_defaults(self):
        for key in FORMERLY_MISSING_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, DEFAULTS)

    def test_defaults_match_locked_values(self):
        self.assertEqual(DEFAULTS["niche"],
                         "history mysteries investigated with modern tech")
        self.assertEqual(DEFAULTS["channel_name"], "The Deep Scan")
        self.assertEqual(DEFAULTS["narrator_voice"], "bm_george")
        self.assertEqual(DEFAULTS["narrator_tier"], "local")
        self.assertEqual(DEFAULTS["narrator_speed"], 0.9)
        self.assertEqual(DEFAULTS["channel_timezone"], "America/Chicago")
        self.assertEqual(DEFAULTS["niche_lock_days"], 90)
        self.assertEqual(DEFAULTS["long_videos_per_day"], 1)
        self.assertEqual(DEFAULTS["shorts_per_day"], 2)
        self.assertEqual(DEFAULTS["long_video_bitrate"], "12M")
        self.assertEqual(DEFAULTS["series_enabled"], False)
        self.assertEqual(DEFAULTS["series_name"], "")

    def test_load_config_on_real_file_matches_defaults_for_locked_keys(self):
        config = load_config(str(CONFIG_YAML))
        for key in ("niche", "channel_name", "narrator_voice",
                    "narrator_tier", "narrator_speed", "channel_timezone",
                    "niche_lock_days", "long_videos_per_day",
                    "shorts_per_day", "long_video_bitrate"):
            with self.subTest(key=key):
                self.assertEqual(config[key], DEFAULTS[key])


class MissingFileTests(unittest.TestCase):
    def test_missing_file_raises_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "no-such-config.yaml")
            with self.assertRaises(FileNotFoundError) as ctx:
                load_config(missing)
            self.assertIn("no-such-config.yaml", str(ctx.exception))

    def test_missing_file_non_strict_warns_and_returns_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "no-such-config.yaml")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                config = load_config(missing, strict=False)
            self.assertEqual(config["narrator_voice"], "bm_george")
            self.assertTrue(
                any(issubclass(w.category, UserWarning)
                    and "not found" in str(w.message) for w in caught),
                "strict=False on a missing file should still warn loudly")


class UnknownKeyTests(unittest.TestCase):
    def test_unknown_key_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(
                'niche: "history mysteries investigated with modern tech"\n'
                'narrator_voic: "bm_george"\n',
                encoding="utf-8")
            with self.assertWarns(UserWarning) as ctx:
                config = load_config(str(path))
            self.assertIn("narrator_voic", str(ctx.warning))
        # The unknown key is kept in the returned dict (backwards
        # compatible: callers read review_* keys via .get), not dropped.
        self.assertEqual(config["narrator_voic"], "bm_george")

    def test_known_review_keys_do_not_warn(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(
                'niche: "history mysteries investigated with modern tech"\n'
                'review_music_genre: "ambient"\n'
                'review_peak_shift_minutes: 30\n',
                encoding="utf-8")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                load_config(str(path))
            unknown = [str(w.message) for w in caught
                       if "Unknown config key" in str(w.message)]
            self.assertEqual(unknown, [], f"unexpected warnings: {unknown}")


if __name__ == "__main__":
    unittest.main()
