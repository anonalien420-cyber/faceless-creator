"""Contract tests for the ComfyUI client in src/visuals.py.

These are CONTRACT tests against a LOCAL stub HTTP server (python
http.server in this file) that mimics the ComfyUI endpoints the client
actually calls: POST /prompt, GET /history/<prompt_id>, GET /view.
They are NOT live integration tests: no real ComfyUI server, workflow
model, or GPU is involved. Live-server verification is still BLOCKED
(see the module docstring in src/visuals.py and docs/PHASES_1_4.md).
"""
import http.server
import json
import os
import socketserver
import tempfile
import threading
import time
import unittest
import urllib.parse

from src import visuals
from src.visuals import generate_script_assets, generate_scene
from src.visual_qa import check_visual_manifest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
WORKFLOW = os.path.join(FIXTURES, "comfyui_workflow_api.json")

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64

SCENES = [
    {"scene": 1,
     "image_prompt": "Full-colour cartoon reconstruction of a 1914 English cottage garden, two schoolgirls with a paper camera, warm afternoon light",
     "animation_prompt": "Full-colour cartoon animation, slow pan across a 1914 English cottage garden",
     "claim_ids": ["c1", "c2"], "source_ids": ["s1"]},
    {"scene": 2,
     "image_prompt": "Full-colour cartoon reconstruction of a woodland stream with paper fairy cutouts pinned to a branch",
     "animation_prompt": "Full-colour cartoon animation, gentle push-in on a woodland stream",
     "claim_ids": ["c2"], "source_ids": ["s1", "s2"]},
]


class StubComfyUIHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, payload, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self.server.requests.append(("POST", parsed.path, raw))
        if parsed.path == "/prompt":
            self.server.prompt_posts += 1
            try:
                self.server.last_prompt = json.loads(raw.decode("utf-8"))
            except ValueError:
                self.server.last_prompt = None
            self._send_json({"prompt_id": "stub-prompt-1", "number": 1,
                             "node_errors": {}})
        else:
            self._send_json({"error": "unknown endpoint"}, status=404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        self.server.requests.append(("GET", parsed.path, b""))
        if parsed.path.startswith("/history/"):
            self.server.history_gets += 1
            prompt_id = urllib.parse.unquote(parsed.path[len("/history/"):])
            mode = self.server.mode
            if mode == "error":
                entry = {"status": {"status_str": "error", "completed": True,
                                    "messages": [["exception_message",
                                                  "KSampler failed: bad seed"]]},
                         "outputs": {}}
            elif mode == "pending":
                entry = {"status": {"status_str": "running", "completed": False},
                         "outputs": {}}
            elif mode == "video":
                entry = {"status": {"status_str": "success", "completed": True},
                         "outputs": {"8": {"videos": [
                             {"filename": "scene-001-video.mp4", "subfolder": "",
                              "type": "output"}]}}}
            else:  # "ok"
                entry = {"status": {"status_str": "success", "completed": True},
                         "outputs": {"7": {"images": [
                             {"filename": "scene-001-image.png", "subfolder": "",
                              "type": "output"}]}}}
            self._send_json({prompt_id: entry})
        elif parsed.path == "/view":
            self.server.view_gets += 1
            self._send_bytes(MP4_BYTES if self.server.mode == "video" else PNG_BYTES)
        else:
            self._send_json({"error": "unknown endpoint"}, status=404)


class StubComfyUIServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address):
        super().__init__(address, StubComfyUIHandler)
        self.mode = "ok"
        self.requests = []
        self.prompt_posts = 0
        self.history_gets = 0
        self.view_gets = 0
        self.last_prompt = None


class ComfyUIContractTests(unittest.TestCase):
    def setUp(self):
        self.server = StubComfyUIServer(("127.0.0.1", 0))
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.05},
                                       daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:{}".format(self.server.server_address[1])
        self._td = tempfile.TemporaryDirectory()
        self.outdir = self._td.name

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._td.cleanup()

    def _script(self, scenes=None):
        return {"topic": "Contract test", "format": "short",
                "scenes": scenes if scenes is not None else [dict(s) for s in SCENES]}

    def _workflow(self):
        with open(WORKFLOW, encoding="utf-8") as fh:
            return json.load(fh)

    def test_workflow_fixture_loads_as_api_format(self):
        workflow = self._workflow()
        self.assertIn("5", workflow)
        self.assertEqual(workflow["5"]["class_type"], "KSampler")
        self.assertEqual(workflow["2"]["inputs"]["text"], "{{PROMPT}}")
        self.assertEqual(workflow["5"]["inputs"]["seed"], "{{SEED}}")

    def test_submit_poll_download_flow_completes(self):
        result = generate_script_assets(self._script(), WORKFLOW, self.base_url,
                                        self.outdir)
        self.assertEqual(len(result["assets"]), 2)
        self.assertEqual(self.server.prompt_posts, 2)
        self.assertGreaterEqual(self.server.view_gets, 2)
        for asset in result["assets"]:
            self.assertTrue(os.path.isfile(asset["path"]))
            self.assertGreater(os.path.getsize(asset["path"]), 0)
            with open(asset["path"], "rb") as fh:
                self.assertEqual(fh.read(8), PNG_BYTES[:8])
        self.assertIn("disclaimer", result)
        self.assertIn("reconstruction", result["disclaimer"].lower())

    def test_prompt_and_seed_substitution_in_submitted_payload(self):
        result = generate_script_assets(self._script(), WORKFLOW, self.base_url,
                                        self.outdir)
        submitted = self.server.last_prompt["prompt"]
        # Positive / negative prompts substituted into the CLIP nodes.
        self.assertEqual(submitted["2"]["inputs"]["text"],
                         SCENES[1]["image_prompt"])
        self.assertEqual(submitted["3"]["inputs"]["text"], visuals.NEGATIVE)
        # Bare {{SEED}} is a numeric node input: submitted as int, and the
        # manifest records exactly the seed that was submitted.
        seed = submitted["5"]["inputs"]["seed"]
        self.assertIsInstance(seed, int)
        self.assertNotIsInstance(seed, bool)
        self.assertEqual(result["assets"][1]["seed"], seed)
        self.assertNotIn("{{PROMPT}}", json.dumps(submitted))
        self.assertNotIn("{{SEED}}", json.dumps(submitted))

    def test_manifest_preserves_claim_source_prompt_seed_disclosure(self):
        result = generate_script_assets(self._script(), WORKFLOW, self.base_url,
                                        self.outdir)
        for scene, asset in zip(SCENES, result["assets"]):
            self.assertEqual(asset["scene"], scene["scene"])
            self.assertEqual(asset["claim_ids"], scene["claim_ids"])
            self.assertEqual(asset["source_ids"], scene["source_ids"])
            self.assertEqual(asset["prompt"], scene["image_prompt"])
            self.assertIsInstance(asset["seed"], int)
            self.assertIn("reconstruction", asset["visual_type"].lower())
            self.assertIn("fingerprint", asset)
        report = check_visual_manifest(self._script(), result)
        self.assertTrue(report["passed"], report)

    def test_resume_skips_regeneration_on_fingerprint_match(self):
        first = generate_script_assets(self._script(), WORKFLOW, self.base_url,
                                       self.outdir)
        self.assertEqual(self.server.prompt_posts, 2)
        second = generate_script_assets(self._script(), WORKFLOW, self.base_url,
                                        self.outdir)
        self.assertEqual(self.server.prompt_posts, 2,
                         "resume must not re-submit matching scenes")
        self.assertEqual([a["path"] for a in first["assets"]],
                         [a["path"] for a in second["assets"]])
        self.assertEqual([a["seed"] for a in first["assets"]],
                         [a["seed"] for a in second["assets"]])
        self.assertEqual([a["fingerprint"] for a in first["assets"]],
                         [a["fingerprint"] for a in second["assets"]])

    def test_prompt_change_regenerates_only_changed_scene(self):
        generate_script_assets(self._script(), WORKFLOW, self.base_url, self.outdir)
        self.assertEqual(self.server.prompt_posts, 2)
        changed = [dict(s) for s in SCENES]
        changed[1]["image_prompt"] = "Full-colour cartoon reconstruction of a different woodland scene"
        result = generate_script_assets(self._script(changed), WORKFLOW,
                                        self.base_url, self.outdir)
        self.assertEqual(self.server.prompt_posts, 3,
                         "only the changed scene should regenerate")
        self.assertNotEqual(result["assets"][1]["fingerprint"],
                            result["assets"][0]["fingerprint"])

    def test_video_media_type_uses_animation_prompt_and_video_output(self):
        self.server.mode = "video"
        result = generate_script_assets(self._script(), WORKFLOW, self.base_url,
                                        self.outdir, media_type="video")
        asset = result["assets"][0]
        self.assertEqual(asset["type"], "video")
        self.assertTrue(asset["path"].endswith(".mp4"))
        self.assertEqual(asset["prompt"], SCENES[0]["animation_prompt"])
        with open(asset["path"], "rb") as fh:
            self.assertEqual(fh.read(8), MP4_BYTES[:8])

    def test_missing_prompt_and_bad_media_type_raise(self):
        with self.assertRaises(ValueError):
            generate_scene({"scene": 1}, {}, self.base_url, self.outdir)
        with self.assertRaises(ValueError):
            generate_scene(SCENES[0], {}, self.base_url, self.outdir,
                           media_type="gif")

    def test_prompt_containing_placeholder_survives_verbatim(self):
        scene = {"scene": 1,
                 "image_prompt": "Full-colour cartoon of a sign reading {{SEED}} in a museum",
                 "claim_ids": ["c1"], "source_ids": ["s1"]}
        generate_script_assets(self._script([scene]), WORKFLOW, self.base_url,
                               self.outdir)
        submitted = self.server.last_prompt["prompt"]
        self.assertIn("{{SEED}}", submitted["2"]["inputs"]["text"],
                      "literal placeholder text inside the scene prompt must not be rewritten")

    def test_server_error_fails_fast_not_timeout(self):
        self.server.mode = "error"
        start = time.monotonic()
        with self.assertRaises(RuntimeError) as ctx:
            generate_scene(SCENES[0], self._workflow(),
                           self.base_url, self.outdir, timeout=30,
                           poll_interval=0.05)
        elapsed = time.monotonic() - start
        self.assertIn("failed", str(ctx.exception))
        self.assertLess(elapsed, 5,
                        "a server-side error must not burn the full timeout")

    def test_timeout_when_generation_never_completes(self):
        self.server.mode = "pending"
        with self.assertRaises(TimeoutError):
            generate_scene(SCENES[0], self._workflow(),
                           self.base_url, self.outdir, timeout=0.3,
                           poll_interval=0.05)

    def test_unreachable_host_fails_loudly(self):
        with self.assertRaises(RuntimeError) as ctx:
            generate_script_assets(self._script(), WORKFLOW,
                                   "http://127.0.0.1:1", self.outdir)
        self.assertIn("127.0.0.1", str(ctx.exception))
        self.assertFalse(os.path.exists(os.path.join(self.outdir, "visual_manifest.json")))
        self.assertEqual(os.listdir(self.outdir), [])

    def test_visual_qa_rejects_tampered_claim_ids(self):
        result = generate_script_assets(self._script(), WORKFLOW, self.base_url,
                                        self.outdir)
        result["assets"][0]["claim_ids"] = ["not-a-claim"]
        report = check_visual_manifest(self._script(), result)
        self.assertFalse(report["passed"])
        self.assertTrue(any("claim" in e for e in report["errors"]))


if __name__ == "__main__":
    unittest.main()
