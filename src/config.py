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

DEFAULTS = {
    "niche": "personal finance tips",
    "niches": [],
    "niche_keywords": [],
    "language": "en",
    "videos_per_run": 3,
    "short_or_long": "short",
    "upload_mode": "draft",
    "channel_name": "YOUR_CHANNEL_NAME_HERE",
    "narrator_voice": "en-US-ChristopherNeural",
    "narrator_tier": "free",
    "narrator_speed": 1.0,
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
}


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


def load_config(path="config.yaml"):
    config = dict(DEFAULTS)
    # Copy mutable defaults so one load never mutates another.
    for key, value in DEFAULTS.items():
        if isinstance(value, list):
            config[key] = list(value)
    current_list_key = None
    current_dict = None
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
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
            if value == "":
                # Start of a list block.
                config[key] = []
                current_list_key = key
                current_dict = None
            else:
                config[key] = _scalar(value)
                current_list_key = None
                current_dict = None
    # Drop empty-string list placeholders (e.g. a single "" URL entry).
    for key in ("music_urls", "stock_image_urls", "stock_video_urls", "peak_windows"):
        config[key] = [v for v in config.get(key, []) if v]
    return config
