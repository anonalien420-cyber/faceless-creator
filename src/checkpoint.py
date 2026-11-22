"""Checkpoint/resume for long renders (Phase 3 item 7).

A daily run renders narration -> music -> transcription -> visuals
-> video -> QA. The video render is the expensive part; if the run
is interrupted partway (crash, timeout, CI kill), the next run with
--resume reuses the finished stages instead of starting over.

A checkpoint (data/checkpoint_<fmt>.json, mode 0600) records, per
stage, the output files and their sha256 hashes, plus a fingerprint
of the inputs that produced them. On resume, a checkpoint is trusted
only after ALL of these pass:
- the file parses and has the current schema version;
- its checksum matches (a half-written or hand-edited file is
  discarded, never trusted);
- its input fingerprint matches the current run's inputs (a changed
  script, voice, music volume, or format invalidates it);
- it is younger than the TTL (default 48 h);
- every recorded output file exists AND its sha256 still matches
  (a deleted, truncated, or replaced output invalidates that stage).

A stage that fails validation is dropped (the rest of the checkpoint
still stands); a bad checksum/fingerprint/TTL discards the whole
checkpoint. The reason is always returned so the run log can say why
a resume did not happen.

QA is NEVER checkpointed: a resumed run always re-runs QA on the
reused video. A checkpoint can only skip work, never a quality gate.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

try:
    from src.secrets import write_private_json
except ImportError:
    from secrets import write_private_json

SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 48 * 3600  # 48 hours


def _canonical(data):
    """Canonical JSON bytes for hashing: sorted keys, no whitespace."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_fingerprint(inputs):
    """sha256 hex of the canonical JSON of `inputs` (a dict of the
    values that determine a render's outputs: format, script content,
    narrator voice/tier/speed, music volume, caption preset, niche).
    Any change to an input changes the fingerprint, so a checkpoint
    from different inputs is never reused."""
    return hashlib.sha256(_canonical(inputs)).hexdigest()


def file_sha256(path):
    """sha256 hex of a file's bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_outputs_valid(stage):
    """(ok, reason): every recorded output exists and still hashes
    to the recorded value. Returns the first failure reason."""
    for path, expected in (stage.get("hashes") or {}).items():
        if not os.path.exists(path):
            return False, f"output missing: {path}"
        try:
            actual = file_sha256(path)
        except OSError as exc:
            return False, f"output unreadable: {path} ({exc})"
        if actual != expected:
            return False, f"output changed since checkpoint: {path}"
    return True, None


def save_checkpoint(path, fingerprint, stages):
    """Write a checkpoint: {schema_version, fingerprint, saved_at,
    checksum, stages}. `stages` maps stage name -> {"outputs": [paths],
    "hashes": {path: sha256}, "finished_at": iso}. The checksum covers
    everything except itself, so tampering or a torn write is
    detectable on load. File is mode 0600."""
    now = datetime.now(timezone.utc).isoformat()
    payload = {"schema_version": SCHEMA_VERSION, "fingerprint": fingerprint,
               "saved_at": now, "stages": stages}
    payload["checksum"] = hashlib.sha256(
        _canonical(payload)).hexdigest()
    write_private_json(path, payload)
    return path


def load_checkpoint(path, fingerprint, ttl_seconds=DEFAULT_TTL_SECONDS,
                    now=None):
    """Load and validate a checkpoint for the given input fingerprint.

    Returns (stages, discard_reason): `stages` is the dict of
    validated stages ({name: stage}) or None when the checkpoint was
    discarded; `discard_reason` is None on success, else a short
    human-readable reason ("no checkpoint", "checksum mismatch",
    "fingerprint mismatch", "stale", ...). Individual stages whose
    outputs fail validation are dropped from `stages` and named in
    the reason (the checkpoint is partially usable, not poisoned).
    """
    if not os.path.exists(path):
        return None, "no checkpoint file"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, f"checkpoint unreadable ({exc})"
    if not isinstance(data, dict):
        return None, "checkpoint is not a JSON object"
    if data.get("schema_version") != SCHEMA_VERSION:
        return None, (f"schema version {data.get('schema_version')} "
                      f"!= {SCHEMA_VERSION}")
    stored_checksum = data.get("checksum")
    check_payload = {k: v for k, v in data.items() if k != "checksum"}
    if not stored_checksum or hashlib.sha256(
            _canonical(check_payload)).hexdigest() != stored_checksum:
        return None, "checksum mismatch — discarding (torn or edited file)"
    if data.get("fingerprint") != fingerprint:
        return None, "input fingerprint mismatch — inputs changed"
    try:
        saved_at = datetime.fromisoformat(data.get("saved_at", ""))
    except ValueError:
        return None, "unparseable saved_at"
    now = now or datetime.now(timezone.utc)
    if saved_at.tzinfo is None:
        saved_at = saved_at.replace(tzinfo=timezone.utc)
    age = (now - saved_at).total_seconds()
    if age < 0 or age > ttl_seconds:
        return None, f"stale checkpoint (age {age:.0f}s > TTL {ttl_seconds}s)"
    stages = data.get("stages") or {}
    if not isinstance(stages, dict):
        return None, "stages is not an object"
    valid, dropped = {}, []
    for name, stage in stages.items():
        if not isinstance(stage, dict):
            dropped.append(f"{name} (malformed)")
            continue
        ok, reason = _stage_outputs_valid(stage)
        if ok:
            valid[name] = stage
        else:
            dropped.append(f"{name} ({reason})")
    if not valid:
        return None, "no stage outputs survived validation: " + "; ".join(dropped)
    reason = ("partial checkpoint — dropped stage(s): " + "; ".join(dropped)) if dropped else None
    return valid, reason


def record_stage(stages, name, output_paths):
    """Record one finished stage into `stages` (in memory): hash
    every output file now, so a later load can prove the files are
    the ones this stage produced. Raises FileNotFoundError when an
    output is missing — a stage that produced nothing is not
    recordable as done."""
    hashes = {}
    for path in output_paths:
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"checkpoint stage {name!r}: output missing: {path}")
        hashes[path] = file_sha256(path)
    stages[name] = {"outputs": list(output_paths), "hashes": hashes,
                    "finished_at": datetime.now(timezone.utc).isoformat()}
    return stages
