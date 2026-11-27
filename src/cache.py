"""Content-hash caching: skip re-TTS / re-render when nothing changed,
and memoize ffprobe so repeated probes of the same asset are free.

Stdlib only. Cache state lives in data/cache.json (a small index of
content-hash -> output path + mtime). An entry is a HIT only when the
recorded output still exists and its size/mtime match what we stored,
so a deleted or rebuilt file is never served stale.

The pipeline is deterministic given the same script text + voice +
visuals, so a hash of those inputs is a safe skip key. Caching is
opt-out (config cache_enabled, default true) and never changes output
content — it only avoids redoing identical work.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess

CACHE_PATH = "data/cache.json"
_PROBE_MEMO: dict = {}


def _load(path: str = CACHE_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save(data: dict, path: str = CACHE_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def make_key(*parts) -> str:
    """Stable hash of arbitrary string/number parts (script text, voice,
    visual list, format, ...). Order matters; None becomes ''."""
    blob = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def _fingerprint(path: str):
    try:
        st = os.stat(path)
        return [st.st_size, int(st.st_mtime)]
    except OSError:
        return None


def is_cached(kind: str, key: str, output: str, path: str = CACHE_PATH) -> bool:
    """True when `output` was previously produced for (kind, key) and is
    still present and unchanged on disk."""
    if not output or not os.path.exists(output):
        return False
    entry = _load(path).get(kind, {}).get(key)
    if not entry or entry.get("output") != output:
        return False
    return entry.get("fingerprint") == _fingerprint(output)


def mark_cached(kind: str, key: str, output: str, path: str = CACHE_PATH) -> None:
    data = _load(path)
    data.setdefault(kind, {})[key] = {"output": output,
                                      "fingerprint": _fingerprint(output)}
    _save(data, path)


def ffprobe_duration(path: str, use_cache: bool = True):
    """Memoized ffprobe container duration (seconds), or None."""
    if use_cache and path in _PROBE_MEMO:
        return _PROBE_MEMO[path]
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True)
        value = float(out.stdout.strip())
    except (ValueError, subprocess.SubprocessError, OSError):
        value = None
    if use_cache:
        _PROBE_MEMO[path] = value
    return value


def clear_probe_memo() -> None:
    _PROBE_MEMO.clear()
