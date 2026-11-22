"""Validators for operator-controlled workflow inputs.

These values arrive from `workflow_dispatch` inputs (or the CLI) and are
passed on to other modules / subprocesses, so they are validated here,
before any queue lookup, API call, or subprocess invocation:

* ``validate_video_id`` — a YouTube video ID is exactly 11 characters
  from ``[A-Za-z0-9_-]``. Anything else (``$(id)``, backticks, short /
  long strings, slashes, spaces) is refused. This is the defence in
  depth behind the crosspost workflow passing the id through ``env:``
  instead of interpolating it into ``run:``.
* ``validate_niche`` — a niche is free text (e.g. "history mysteries
  investigated with modern tech"). A value starting with ``-`` is
  refused: it could be parsed as a flag by a downstream module's
  ``argparse`` parser when the niche is passed on as ``--niche <value>``
  (there is deliberately NO ``--auto-public`` / ``--public`` /
  ``--publish-at-peak`` flag anywhere in this pipeline). An empty
  string means "no explicit niche" and is returned unchanged.

Both raise ``ValueError`` on invalid input and return the (stripped)
value on success, so callers can fail closed with a clear message.
"""

import re

_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}\Z")


def validate_video_id(video_id):
    """Return ``video_id`` if it is a well-formed YouTube video ID.

    Raises ``ValueError`` otherwise — including for command-substitution
    payloads such as ``$(id)`` or backticked commands, which never match
    the 11-character ``[A-Za-z0-9_-]`` shape.
    """
    if not isinstance(video_id, str) or not _VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError(
            f"invalid YouTube video id: {video_id!r} "
            "(expected exactly 11 characters from [A-Za-z0-9_-])")
    return video_id


def validate_niche(niche):
    """Return ``niche`` (stripped) if it is safe to pass on as a value.

    An empty string means "no explicit niche" and is returned as-is.
    A value starting with ``-`` (e.g. ``--auto-public``, ``--public``)
    is refused: it could be parsed as a flag by a downstream
    ``argparse`` parser. Control characters are refused for the same
    reason (they must never reach a subprocess argument list or log).
    """
    if not isinstance(niche, str):
        raise ValueError(f"invalid niche: {niche!r} (expected a string)")
    value = niche.strip()
    if not value:
        return ""
    if value.startswith("-"):
        raise ValueError(
            f"invalid niche: {value!r} (must not start with '-'; "
            "flag-like values are refused)")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError("invalid niche: control characters are not allowed")
    return value
