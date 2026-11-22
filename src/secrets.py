"""Secret handling for the Deep Scan pipeline (Phase 3 item 6).

Two guarantees, both tested in tests/test_secrets.py:

1. Redaction: a secret value must never reach a log line, a QA
   report, a job-state file, or a diagnostic artifact. Secrets enter
   this codebase only through environment variables (PEXELS_API_KEY,
   PIXABAY_API_KEY, YT_API_KEY, TIKTOK_RESEARCH_TOKEN,
   FACEBOOK_GRAPH_TOKEN, ELEVENLABS_API_KEY) and through the OAuth
   token files token.json / client_secrets.json (never logged, never
   in config.yaml). `redact()` replaces every currently-set secret
   value, plus generic patterns for secrets embedded in URLs
   (YouTube/Pixabay put `key=` in the query string, so a failed
   request's exception message carries the full URL) and in
   Authorization / xi-api-key headers.

2. Private files: state and diagnostic files the pipeline writes
   are mode 0600 (owner read/write only). token.json already was
   (src/upload.py:_save_token); the same treatment now applies to
   job_state.json, ffmpeg diagnostics, the narration fallback marker,
   the run log, and the series state file.

Callers: job_state.record() / persist_diagnostic() /
run_with_retries() redact before persisting; trends._fetch_json and
the stock-video collectors redact the exception before printing it;
narrate.record_narration_fallback / append_run_log and
run.py's series-state write use write_private_json.
"""
import json
import os
import re

# Env vars that carry secrets in this repo. Values are read at
# redact() time (not import time) so tests can set/unset them.
SECRET_ENV_VARS = (
    "PEXELS_API_KEY",
    "PIXABAY_API_KEY",
    "YT_API_KEY",
    "TIKTOK_RESEARCH_TOKEN",
    "FACEBOOK_GRAPH_TOKEN",
    "ELEVENLABS_API_KEY",
)

REDACTED = "[REDACTED]"

# Generic patterns for secrets that never pass through the env vars
# above (a key embedded in a request URL, a bearer token, an API-key
# header in a repr'd request/exception).
_GENERIC_PATTERNS = (
    # ?key=... or &key=... in a URL (YouTube Data API, Pixabay).
    re.compile(r"(?i)([?&]key=)[^&\s\"'<>]+"),
    # Authorization: Bearer <token> (TikTok Research API).
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/=]{8,}"),
    # Authorization: <scheme> <token> generally.
    re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)"
               r"[A-Za-z0-9._\-~+/=]{8,}"),
    # xi-api-key header (ElevenLabs).
    re.compile(r"(?i)(xi-api-key[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+"),
    # Pexels "Authorization: <key>" header.
    re.compile(r"(?i)(['\"]authorization['\"]\s*:\s*['\"])"
               r"[^\"']{8,}"),
)

# Minimum length for an exact-value replacement: short values (e.g.
# "test") would redact innocent words. Real keys/tokens are long.
_MIN_SECRET_LEN = 8


def known_secret_values():
    """Secret values currently set in the environment (never logged)."""
    return [value for name in SECRET_ENV_VARS
            if (value := os.environ.get(name))]


def redact(text, extra=()):
    """Return `text` with every known secret value and every generic
    secret pattern replaced by [REDACTED].

    `extra` lets a caller redact a value it holds locally (e.g. a
    token read from a file) without putting it in the environment.
    Non-string input is stringified; None stays None.
    """
    if text is None:
        return None
    out = str(text)
    for value in list(known_secret_values()) + list(extra or ()):
        if value and len(str(value)) >= _MIN_SECRET_LEN:
            out = out.replace(str(value), REDACTED)
    for pattern in _GENERIC_PATTERNS:
        out = pattern.sub(r"\1" + REDACTED, out)
    return out


def redact_mapping(data, extra=()):
    """Recursively redact strings inside dicts/lists/tuples (QA
    reports, job state, diagnostic JSON). Other values pass through
    unchanged. Returns a new structure."""
    if isinstance(data, str):
        return redact(data, extra)
    if isinstance(data, dict):
        return {key: redact_mapping(value, extra)
                for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [redact_mapping(value, extra) for value in data]
    return data


def write_private_text(path, text):
    """Atomically write `text` to `path` with mode 0600 (owner
    read/write only), even when the process umask is permissive.
    The mode is set on the temp file before the rename, so the
    file is never world-readable, even briefly."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def write_private_json(path, data):
    """Atomically write JSON `data` to `path` with mode 0600."""
    return write_private_text(path, json.dumps(data, indent=2))
