"""Atomic run checkpoints and bounded retry helpers for production steps."""
import json
import os
import random
import re
import time
from datetime import datetime, timezone

try:
    from src.secrets import redact, write_private_text
except ImportError:  # run as a top-level module (tests import both ways)
    from secrets import redact, write_private_text

# Where complete subprocess diagnostics are persisted on failure.
# FFmpeg stderr can run to tens of kilobytes; truncating it into
# job_state.json / CI logs made the Nov 8 and Nov 16 failures
# undiagnosable, so the full text is written to a file artifact and
# only a reference + tail is kept in the state / log lines.
DIAGNOSTICS_DIR = "data/ffmpeg_diagnostics"


def _diagnostic_filename(step):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(step)).strip("-") or "step"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{safe}-{ts}-{os.getpid()}.log"


def persist_diagnostic(step, text, diagnostics_dir=None):
    """Persist the COMPLETE diagnostic text to a file artifact.

    Returns the artifact path. Never truncates: the full text is
    written verbatim so a failure can be diagnosed after the run.
    `diagnostics_dir` defaults to DEEP_SCAN_FFMPEG_DIAGNOSTICS_DIR
    or data/ffmpeg_diagnostics (relative to the run's working dir).
    The text is REDACTED first (a failing command can echo a secret
    into stderr) and the file is mode 0600.
    """
    directory = diagnostics_dir or os.environ.get(
        "DEEP_SCAN_FFMPEG_DIAGNOSTICS_DIR", DIAGNOSTICS_DIR)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, _diagnostic_filename(step))
    write_private_text(path, redact(text))
    return path


class JobState:
    def __init__(self, path="data/job_state.json", run_id=None):
        self.path = path
        self.data = {"schema_version": 1, "run_id": run_id or
                     datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                     "steps": {}}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    old = json.load(fh)
                if (old.get("schema_version") == 1 and isinstance(old.get("steps"), dict)
                        and (run_id is None or old.get("run_id") == run_id)):
                    self.data = old
            except (OSError, ValueError):
                pass

    def record(self, name, status, detail=""):
        # Redact before persisting: a subprocess tail can carry a
        # secret (e.g. a key embedded in a request URL).
        self.data.setdefault("steps", {})[name] = {
            "status": status, "detail": redact(str(detail))[:2000],
            "updated_at": datetime.now(timezone.utc).isoformat()}
        self.save()

    def succeeded(self, name):
        return self.data.get("steps", {}).get(name, {}).get("status") == "success"

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        # State files can hold redacted diagnostic tails; keep them
        # owner-only even under a permissive umask.
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)


def run_with_retries(command, step, state=None, attempts=3, backoff=2,
                     runner=None, sleep=time.sleep):
    """Run a subprocess with bounded exponential retry and checkpoint status."""
    import subprocess
    runner = runner or subprocess.run
    attempts = max(1, min(int(attempts), 5))
    last = None
    last_artifact = None
    for attempt in range(1, attempts + 1):
        last = runner(command, capture_output=True, text=True)
        if last.returncode == 0:
            if state:
                state.record(step, "success", "attempt {}".format(attempt))
            return last
        full = last.stderr or last.stdout or ""
        try:
            last_artifact = persist_diagnostic(
                "{}-attempt{}".format(step, attempt), full)
        except OSError:
            last_artifact = None
        if last_artifact:
            detail = ("attempt {} exit {}: full diagnostic saved to {} "
                      "(tail: {})".format(attempt, last.returncode,
                                          last_artifact, full[-1200:]))
        else:
            detail = "attempt {} exit {}: {}".format(
                attempt, last.returncode, full[-1500:])
        if state:
            state.record(step, "retrying" if attempt < attempts else "failed", detail)
        if attempt < attempts:
            sleep(min(30, backoff * (2 ** (attempt - 1)) + random.random()))
    tail = redact((last.stderr or last.stdout or "unknown error")[-2000:])
    if last_artifact:
        raise RuntimeError("{} failed after {} attempt(s): full diagnostic "
                           "saved to {}\n{}".format(
                               step, attempts, last_artifact, tail))
    raise RuntimeError("{} failed after {} attempt(s): {}".format(
        step, attempts, tail))
