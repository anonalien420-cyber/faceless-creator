"""Music bed volume comes from config (Phase 3, item 2).

The mellow history bed mixes at 0.06 under the narration. That level
is locked in config.yaml (music_volume) and mirrored in
src/config.py DEFAULTS; the --music-volume CLI flag still overrides
it for a one-off mix. Out-of-range values fail loudly, never clamp
silently.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import DEFAULTS, load_config
from src.music import resolve_music_volume, validate_music_volume

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MusicVolumeConfigTests(unittest.TestCase):
    def test_config_yaml_locks_bed_at_006(self):
        config = load_config(os.path.join(REPO_ROOT, "config.yaml"))
        self.assertEqual(config.get("music_volume"), 0.06)

    def test_defaults_lock_bed_at_006(self):
        self.assertEqual(DEFAULTS.get("music_volume"), 0.06)

    def test_resolve_uses_config_when_no_cli_value(self):
        volume, source = resolve_music_volume(None, {"music_volume": 0.06})
        self.assertEqual(volume, 0.06)
        self.assertEqual(source, "config")

    def test_resolve_cli_overrides_config(self):
        volume, source = resolve_music_volume(0.12, {"music_volume": 0.06})
        self.assertEqual(volume, 0.12)
        self.assertEqual(source, "cli")

    def test_resolve_defaults_to_006_without_config(self):
        volume, source = resolve_music_volume(None, {})
        self.assertEqual(volume, 0.06)
        self.assertEqual(source, "default")
        volume, source = resolve_music_volume(None, None)
        self.assertEqual(volume, 0.06)
        self.assertEqual(source, "default")

    def test_validate_rejects_zero_negative_and_above_one(self):
        for bad in (0, 0.0, -0.1, 1.5, 2.0, "loud", None, float("nan")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_music_volume(bad)

    def test_validate_accepts_boundaries(self):
        self.assertEqual(validate_music_volume(1.0), 1.0)
        self.assertEqual(validate_music_volume(0.001), 0.001)
        self.assertEqual(validate_music_volume("0.06"), 0.06)

    def test_run_py_passes_config_volume_to_music(self):
        # The daily path must not rely on a CLI default: run.py
        # passes the config value explicitly to src.music.
        with open(os.path.join(REPO_ROOT, "src", "run.py"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('"--music-volume"', text)
        self.assertIn('config.get("music_volume", 0.06)', text)


if __name__ == "__main__":
    unittest.main()
