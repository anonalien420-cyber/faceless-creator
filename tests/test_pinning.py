"""Tests for Phase 3 item 5: dependency + Actions pinning.

- requirements.txt: every dependency pinned with == (no floating
  versions), so a fresh install reproduces the tested versions.
- .github/workflows/*.yml: every `uses:` references a full 40-hex
  commit SHA, never a floating tag (v4/v5); the SHAs are the exact
  ones verified against the GitHub API for the tagged releases.
- CI's pip-audit/bandit installs are pinned too (they were unpinned
  before this phase).
"""
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# SHAs verified against the GitHub API (api.github.com/repos/<repo>/
# git/refs/tags/<tag>) on 2026-11-21. If an action ships a new
# release, update both the workflow and this map together.
EXPECTED_SHAS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",  # v4
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",  # v5
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",  # v4
}

SHA_RE = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([0-9a-f]{40})\b")
FLOATING_RE = re.compile(r"uses:\s*\S+@v\d+\b")


class RequirementsPinTests(unittest.TestCase):
    def _requirements(self):
        path = os.path.join(REPO_ROOT, "requirements.txt")
        with open(path, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh]
        return [ln for ln in lines if ln and not ln.startswith("#")]

    def test_every_dependency_pinned(self):
        reqs = self._requirements()
        self.assertTrue(reqs, "requirements.txt has no dependencies")
        for line in reqs:
            self.assertRegex(
                line, r"^[A-Za-z0-9_.\-]+==[0-9][A-Za-z0-9_.\-]*$",
                f"unpinned or malformed requirement: {line!r}")

    def test_numpy_pin_stays_3_11_compatible(self):
        # CI runs Python 3.11; numpy 2.5.x needs >=3.12.
        reqs = dict(ln.split("==") for ln in self._requirements())
        self.assertEqual(reqs.get("numpy"), "2.4.6")

    def test_known_pins(self):
        reqs = dict(ln.split("==") for ln in self._requirements())
        self.assertEqual(reqs.get("kokoro"), "0.9.4")
        self.assertEqual(reqs.get("soundfile"), "0.14.0")
        self.assertEqual(reqs.get("Pillow"), "13.0.0")
        self.assertEqual(reqs.get("requests"), "2.34.2")


class WorkflowPinTests(unittest.TestCase):
    def _workflow_files(self):
        wf_dir = os.path.join(REPO_ROOT, ".github", "workflows")
        return sorted(os.path.join(wf_dir, f) for f in os.listdir(wf_dir)
                      if f.endswith((".yml", ".yaml")))

    def test_all_uses_pinned_to_sha(self):
        for path in self._workflow_files():
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotRegex(text, FLOATING_RE,
                                f"floating action tag in {path}")
            for match in re.finditer(r"uses:\s*(\S+)", text):
                ref = match.group(1)
                m = SHA_RE.match(ref)
                self.assertIsNotNone(
                    m, f"action not pinned to a full SHA in {path}: {ref}")
                action, sha = m.group(1), m.group(2)
                if action in EXPECTED_SHAS:
                    self.assertEqual(
                        sha, EXPECTED_SHAS[action],
                        f"{action} SHA in {path} does not match the "
                        f"verified release SHA")

    def test_no_other_floating_action_refs(self):
        # Every `uses:` in every workflow must be a SHA pin, even for
        # actions outside EXPECTED_SHAS (none today, but the rule is
        # the point).
        for path in self._workflow_files():
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if "uses:" in line:
                        self.assertRegex(line, r"@[0-9a-f]{40}\b",
                                         f"unpinned action in {path}: {line!r}")

    def test_ci_security_tools_pinned(self):
        path = os.path.join(REPO_ROOT, ".github", "workflows",
                            "deep-scan-tests.yml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("pip-audit==2.10.1", text)
        self.assertIn("bandit==1.9.4", text)
        self.assertNotIn("pip install pip-audit bandit", text)


if __name__ == "__main__":
    unittest.main()
