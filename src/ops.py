"""Operational safety: state backup/restore + API quota tracking.

- backup/restore: the pipeline's memory (niche lock, series state, topic
  history, cache, upload feedback, review history, video stats) lives in
  data/. `faceless backup` snapshots those JSON files into one tar.gz;
  `faceless restore` puts them back. Losing the niche lock or topic
  history silently changes channel behaviour — back them up.
- quota tracking: every counted YouTube/stock API call increments a
  daily counter (data/api_usage.json). `quota_status` warns before a
  configured daily budget is exhausted, so a run degrades to manual
  input instead of dying mid-pipeline on a 403 quotaExceeded.
"""

from __future__ import annotations

import json
import os
import tarfile
from datetime import datetime, timezone

STATE_FILES = (
    "data/niche_lock.json",
    "data/series_state.json",
    "data/topic_history.json",
    "data/cache.json",
    "data/upload_feedback.json",
    "data/review_history.json",
    "data/video_stats.json",
    "data/api_usage.json",
)
USAGE_PATH = "data/api_usage.json"
# YouTube Data API default quota is 10,000 units/day; a search costs 100.
DEFAULT_DAILY_BUDGET = {"youtube": 9000, "pexels": 180, "pixabay": 90}


def backup_state(dest="data/backups", state_files=STATE_FILES):
    """Tar.gz the pipeline state files that exist. Returns the archive path."""
    os.makedirs(dest, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(dest, f"faceless-state-{stamp}.tar.gz")
    # Second-resolution stamps collide when two backups land in the same
    # second (tests, rapid retries). Suffix until the name is unique so
    # prune_backups() sees every archive instead of one overwritten file.
    counter = 1
    while os.path.exists(path):
        path = os.path.join(dest, f"faceless-state-{stamp}-{counter}.tar.gz")
        counter += 1
    with tarfile.open(path, "w:gz") as tar:
        for file in state_files:
            if os.path.exists(file):
                tar.add(file)
    return path


def restore_state(archive, state_files=STATE_FILES):
    """Restore state files from a backup archive.

    Only members that are in the known state-file list are extracted
    (no path traversal from a hostile archive). Returns restored paths."""
    allowed = set(state_files)
    restored = []
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name.lstrip("./")
            if name in allowed and member.isfile():
                os.makedirs(os.path.dirname(name) or ".", exist_ok=True)
                with tar.extractfile(member) as src, open(name, "wb") as dst:
                    dst.write(src.read())
                restored.append(name)
    return restored


def prune_backups(dest="data/backups", keep=14):
    """Keep only the newest `keep` state archives. Returns removed paths."""
    if keep < 1 or not os.path.isdir(dest):
        return []
    archives = sorted(
        (os.path.join(dest, name) for name in os.listdir(dest)
         if name.startswith("faceless-state-") and name.endswith(".tar.gz")),
        key=os.path.getmtime)
    removed = []
    for path in archives[:-keep] if len(archives) > keep else []:
        try:
            os.remove(path)
            removed.append(path)
        except OSError:
            pass
    return removed


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def track_api_call(service, units=1, path=USAGE_PATH):
    """Increment today's usage counter for a service. Daily reset is
    implicit: a new date starts a fresh counter dict."""
    usage = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                usage = json.load(fh)
        except (OSError, ValueError):
            usage = {}
    if usage.get("date") != _today():
        usage = {"date": _today(), "services": {}}
    services = usage.setdefault("services", {})
    services[service] = services.get(service, 0) + units
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(usage, fh, indent=2)
    return services[service]


def quota_status(service, budget=None, path=USAGE_PATH):
    """Return {service, used, budget, remaining, warn}. warn=True at >=80%
    of the daily budget so callers can fall back before a hard 403."""
    budget = budget if budget is not None else DEFAULT_DAILY_BUDGET.get(service, 1000)
    used = 0
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                usage = json.load(fh)
            if usage.get("date") == _today():
                used = usage.get("services", {}).get(service, 0)
        except (OSError, ValueError):
            pass
    remaining = max(0, budget - used)
    return {"service": service, "used": used, "budget": budget,
            "remaining": remaining, "warn": used >= 0.8 * budget}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="State backup/restore + quota status.")
    parser.add_argument("action", choices=["backup", "restore", "quota"])
    parser.add_argument("--archive", default="", help="Archive to restore (restore action).")
    parser.add_argument("--dest", default="data/backups")
    parser.add_argument("--service", default="youtube")
    args = parser.parse_args(argv)
    if args.action == "backup":
        path = backup_state(args.dest)
        print(f"State backup -> {path}")
        return 0
    if args.action == "restore":
        if not args.archive or not os.path.exists(args.archive):
            print("ERROR: --archive must point to an existing backup.", flush=True)
            return 1
        restored = restore_state(args.archive)
        print(f"Restored {len(restored)} state file(s): {', '.join(restored) or 'none'}")
        return 0
    status = quota_status(args.service)
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
