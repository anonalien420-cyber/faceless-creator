"""Atomic run checkpoints and bounded retry helpers for production steps."""
import json
import os
import random
import time
from datetime import datetime, timezone


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
        self.data.setdefault("steps", {})[name] = {
            "status": status, "detail": str(detail)[:2000],
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
        os.replace(tmp, self.path)


def run_with_retries(command, step, state=None, attempts=3, backoff=2,
                     runner=None, sleep=time.sleep):
    """Run a subprocess with bounded exponential retry and checkpoint status."""
    import subprocess
    runner = runner or subprocess.run
    attempts = max(1, min(int(attempts), 5))
    last = None
    for attempt in range(1, attempts + 1):
        last = runner(command, capture_output=True, text=True)
        if last.returncode == 0:
            if state:
                state.record(step, "success", "attempt {}".format(attempt))
            return last
        detail = "attempt {} exit {}: {}".format(
            attempt, last.returncode, (last.stderr or last.stdout or "")[-1500:])
        if state:
            state.record(step, "retrying" if attempt < attempts else "failed", detail)
        if attempt < attempts:
            sleep(min(30, backoff * (2 ** (attempt - 1)) + random.random()))
    raise RuntimeError("{} failed after {} attempt(s): {}".format(
        step, attempts, (last.stderr or last.stdout or "unknown error")[-2000:]))
