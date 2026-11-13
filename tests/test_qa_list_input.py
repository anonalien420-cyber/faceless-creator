"""Regression tests for the QA CLI list-input crash (found 2026-11-12
during the end-to-end synthetic production run).

Pipeline script files are JSON lists (scripts_long/shorts.json and
documentary packages are both lists). Passing one to
``python -m src.qa --script-json`` crashed ``check_accuracy`` with
``AttributeError: 'list' object has no attribute 'get'``. The CLI now
unwraps lists, and ``check_accuracy`` treats any non-dict script as
not-applicable instead of crashing.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src.qa import check_accuracy, main


class QaListInputTests(unittest.TestCase):
    def test_check_accuracy_list_is_not_applicable_not_crash(self):
        checks = check_accuracy([{"topic": "x"}])
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["check"], "accuracy_applies")
        self.assertEqual(checks[0]["status"], "pass")

    def test_check_accuracy_non_dict_is_not_applicable(self):
        for bad in (None, "a string", 42):
            with self.subTest(bad=bad):
                checks = check_accuracy(bad)
                self.assertEqual(checks[0]["status"], "pass")

    def test_check_accuracy_plain_dict_without_style_is_not_applicable(self):
        checks = check_accuracy({"topic": "x", "text": "hello"})
        self.assertEqual(checks[0]["check"], "accuracy_applies")
        self.assertEqual(checks[0]["status"], "pass")

    def test_cli_unwraps_single_element_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scripts.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([{"topic": "T", "text": "hello"}], fh)
            with patch("src.qa.run_qa", return_value=True) as mocked:
                self.assertEqual(
                    main(["--video", "v.mp4", "--script-json", path,
                          "--title", "T",
                          "--report", os.path.join(tmp, "qa.json")]), 0)
            script = mocked.call_args.kwargs["script"]
            self.assertIsInstance(script, dict)
            self.assertEqual(script["topic"], "T")

    def test_cli_picks_list_entry_matching_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scripts.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([{"topic": "A", "text": "a"},
                           {"topic": "B", "text": "b"}], fh)
            with patch("src.qa.run_qa", return_value=True) as mocked:
                self.assertEqual(
                    main(["--video", "v.mp4", "--script-json", path,
                          "--title", "B",
                          "--report", os.path.join(tmp, "qa.json")]), 0)
            self.assertEqual(mocked.call_args.kwargs["script"]["topic"], "B")


if __name__ == "__main__":
    unittest.main()
