"""`faceless doctor` — one readiness report for the whole pipeline.

Checks the environment (Python, ffmpeg/ffprobe, fonts, optional deps),
the config (fail-fast validation), optional API keys (presence only,
never printed), and that the data dir is writable. Exit code 0 when all
required checks pass; 1 otherwise. Optional items are reported as
warnings, never failures — the $0 default must stay runnable.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys

REQUIRED_TOOLS = ("ffmpeg", "ffprobe")
OPTIONAL_MODULES = {
    "PIL": "thumbnails (pip install Pillow)",
    "yaml": "full YAML config (pip install PyYAML)",
    "edge_tts": "free neural narration (pip install edge-tts)",
    "googleapiclient": "YouTube upload/stats (pip install google-api-python-client)",
}
OPTIONAL_KEYS = ("YT_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY",
                 "ELEVENLABS_API_KEY", "LLM_API_KEY")


def run_checks(config_path="config.yaml"):
    """Return a list of {check, status, detail}. status: pass/warn/fail."""
    checks = []

    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    add("python", "pass" if sys.version_info >= (3, 11) else "fail",
        f"Python {sys.version.split()[0]} (needs >= 3.11)")
    for tool in REQUIRED_TOOLS:
        found = shutil.which(tool)
        add(tool, "pass" if found else "fail",
            found or "not on PATH — install ffmpeg (apt/brew) or use the Docker image")
    # Fonts: DejaVu drives captions/cards/thumbnails.
    font_ok = any(os.path.exists(os.path.join(d, "DejaVuSans-Bold.ttf"))
                  for d in ("/usr/share/fonts/truetype/dejavu",
                            "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF"))
    add("dejavu_fonts", "pass" if font_ok else "warn",
        "DejaVu found" if font_ok else "DejaVu not found — captions fall back to a default font")
    for module, why in OPTIONAL_MODULES.items():
        ok = importlib.util.find_spec(module) is not None
        add(f"module:{module}", "pass" if ok else "warn",
            "installed" if ok else f"missing — {why}")
    try:
        try:
            from src.config import load_config, validate_config
        except ImportError:
            from config import load_config, validate_config
        errors = validate_config(load_config(config_path))
        add("config", "fail" if errors else "pass",
            "; ".join(errors) if errors else f"{config_path} valid")
    except Exception as exc:
        add("config", "fail", str(exc))
    for key in OPTIONAL_KEYS:
        add(f"key:{key}", "pass" if os.environ.get(key) else "warn",
            "set" if os.environ.get(key) else "not set (optional feature disabled)")
    try:
        os.makedirs("data", exist_ok=True)
        probe = os.path.join("data", ".doctor_write_test")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        add("data_writable", "pass", "data/ is writable")
    except OSError as exc:
        add("data_writable", "fail", str(exc))
    return checks


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Pipeline readiness report.")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args(argv)
    checks = run_checks(args.config)
    failed = [c for c in checks if c["status"] == "fail"]
    warned = [c for c in checks if c["status"] == "warn"]
    for c in checks:
        mark = {"pass": "OK  ", "warn": "WARN", "fail": "FAIL"}[c["status"]]
        print(f"[{mark}] {c['check']}: {c['detail']}")
    print(f"\n{len(checks) - len(failed) - len(warned)} pass, "
          f"{len(warned)} warn, {len(failed)} fail")
    if failed:
        print("Required checks failed — fix the FAIL items above.", file=sys.stderr)
        return 1
    print("Ready. Optional WARN items only disable their own features.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
