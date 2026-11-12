"""Minimal YAML-subset config loader (stdlib only).

Handles the flat structure used by config.yaml: scalar key: value pairs
(strings, ints, booleans) and top-level lists written as:
    key:
      - item
      - item
It also handles lists of mappings, used by music_library:
    music_library:
      - file: "music/example.mp3"
        genre: "pop"
        tempo_bpm: 125
        mood: "upbeat"
        license: "royalty-free"
It is deliberately not a full YAML parser. If you need full YAML, install
PyYAML and replace this loader — the rest of the code only uses the dict
this function returns.
"""

import warnings

# DEFAULTS must mirror config.yaml exactly: these are the values the
# pipeline falls back to for any key the file does not set, so a stale
# default here silently reverts a locked choice (niche, narrator,
# channel name). If you add a key to config.yaml, add it here too —
# tests/test_config_regressions.py enforces that every key config.yaml
# sets exists in DEFAULTS.
DEFAULTS = {
    "niche": "history mysteries investigated with modern tech",
    "niches": [],
    "niche_keywords": [],
    "channel_timezone": "America/Chicago",
    "peak_windows": [],
    "language": "en",
    "videos_per_run": 3,
    "series_name": "",
    "series_enabled": False,
    "niche_lock_days": 90,
    "channel_promise": "Unsolved history and mysteries from around the world, investigated with modern tech — lost cities, events nobody can fully explain, and artifacts that shouldn't exist, reconstructed and tested with today's tools.",
    "long_videos_per_day": 1,
    "shorts_per_day": 2,
    "short_or_long": "short",
    "upload_mode": "draft",
    "channel_name": "The Deep Scan",
    "narrator_voice": "bm_george",
    "narrator_tier": "local",
    "narrator_speed": 0.9,
    "narrator_pause_ms": 350,
    "music_file": "",
    "music_urls": [],
    "music_library": [],
    "licensed_track": "",
    "license_note": "",
    "stock_image_urls": [],
    "stock_video_urls": [],
    "visual_quality": "hd",
    "visual_source": "stock_video",
    "min_resolution": 1080,
    "video_bitrate": "10M",
    "long_video_bitrate": "12M",
    "reddit_subreddits": [],
}

# Keys that are NOT in DEFAULTS but are legitimate in config.yaml:
# src/review.py writes these review_* adjustments into config.yaml and
# src/music.py / src/scheduler.py / src/script.py read them back.
# They are whitelisted here so a post-review config.yaml does not trip
# the unknown-key warning below.
KNOWN_EXTRA_KEYS = frozenset({
    "review_preferred_niche",
    "review_preferred_hook_style",
    "review_preferred_length_seconds",
    "review_music_genre",
    "review_music_tempo_bpm",
    "review_music_mood",
    "review_peak_shift_minutes",
})


def _scalar(value):
    value = value.strip()
    if value in ("", "~", "null"):
        return ""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def load_config(path="config.yaml", strict=True):
    """Load config.yaml over DEFAULTS.

    Missing file: raises FileNotFoundError when strict (the default).
    A missing config used to silently return DEFAULTS, which reverted
    the locked niche/narrator/channel to stale placeholder values with
    no trace — that silent fallback is the Blocker-3 regression this
    fix removes. strict=True is safe as the default: verified 2026-11-12
    that no existing test calls load_config() at all, and every caller
    in src/ is a CLI entry point whose --config defaults to a
    config.yaml that ships in the repo. Pass strict=False only when a
    caller deliberately wants defaults for a missing file (e.g. a
    probe); it still warns so the fallback is visible.
    """
    config = dict(DEFAULTS)
    # Copy mutable defaults so one load never mutates another.
    for key, value in DEFAULTS.items():
        if isinstance(value, list):
            config[key] = list(value)
    current_list_key = None
    current_dict = None
    seen_keys = set()
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        if strict:
            raise FileNotFoundError(
                f"Config file not found: {path!r}. Refusing to run on "
                "placeholder defaults — create it (see config.yaml in "
                "the repo) or pass --config <path>."
            ) from None
        warnings.warn(
            f"Config file not found: {path!r}; using built-in defaults.",
            UserWarning,
            stacklevel=2,
        )
        return config
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indented = line[:1] in (" ", "\t")
        if stripped.startswith("- ") and current_list_key is not None:
            # List item (indented in config.yaml); may start a mapping ("- file: x").
            if current_list_key is None:
                continue
            item = stripped[2:].strip()
            if item.startswith(('"', "'")):
                # Quoted scalar (e.g. - "shorts:weekday:12:00-14:00"):
                # colons inside the quotes are data, NOT a mapping key.
                # (Without this, peak_windows entries parsed as mappings
                # and the scheduler silently fell back to its defaults.)
                config[current_list_key].append(_scalar(item))
                current_dict = None
            elif ":" in item:
                key, _, value = item.partition(":")
                current_dict = {key.strip(): _scalar(value)}
                config[current_list_key].append(current_dict)
            else:
                config[current_list_key].append(_scalar(item))
                current_dict = None
            continue
        if indented and current_dict is not None and ":" in stripped:
            # Continuation line of the current list mapping.
            key, _, value = stripped.partition(":")
            current_dict[key.strip()] = _scalar(value)
            continue
        if ":" in stripped and not indented:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            seen_keys.add(key)
            if value == "":
                # Start of a list block.
                config[key] = []
                current_list_key = key
                current_dict = None
            else:
                config[key] = _scalar(value)
                current_list_key = None
                current_dict = None
    # Warn (stderr, via the warnings module) for keys the loader does not
    # know, instead of silently ignoring them — a typo'd key (e.g.
    # "narrator_voic") previously did nothing and the default silently
    # won. Unknown keys are still kept in the returned dict for
    # backwards compatibility (callers read review_* keys via .get).
    for key in sorted(seen_keys - set(DEFAULTS) - set(KNOWN_EXTRA_KEYS)):
        warnings.warn(
            f"Unknown config key {key!r} in {path!r} — check for a typo; "
            "it is kept as-is but no pipeline step reads it.",
            UserWarning,
            stacklevel=2,
        )
    # Drop empty-string list placeholders (e.g. a single "" URL entry).
    for key in ("music_urls", "stock_image_urls", "stock_video_urls", "peak_windows"):
        config[key] = [v for v in config.get(key, []) if v]
    return config
