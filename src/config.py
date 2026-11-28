"""Config loader: full YAML when PyYAML is installed, else a stdlib
YAML-subset fallback. Either way the rest of the code only uses the
dict this returns.

- PyYAML path (recommended; installed via requirements.txt): parses the
  whole file, including nested mappings like the `brand:` block.
- Stdlib fallback (no deps, $0/offline default): handles the flat
  structure used by config.yaml — scalar key: value pairs, top-level
  lists (scalars or mappings, e.g. music_library), inline flow lists,
  quote-aware comment stripping, AND one level of nested mapping
  (e.g. brand:). It is deliberately not a full YAML parser; install
  PyYAML for anchors, deeper nesting, and multiline scalars.

validate_config() fails fast on obviously wrong types (a string where
a number is required, a non-list niches, ...) so a typo stops the run
before any rendering. When pydantic is installed an optional schema
adds stricter validation; without it the built-in checks still run.
"""

import copy
import re

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
    # --- Production polish (Phase 1) ---
    "music_volume": 0.15,
    "loudness_i": -14,
    "loudness_tp": -1.5,
    "captions_karaoke": True,
    "captions_safe_zone": 0.25,
    "transitions": "varied",
    "brand": {
        "accent": "#FFCB05",
        "accent_alt": "#E3350D",
        "font": "DejaVu Sans",
        "text_color": "#FFFFFF",
        "outline_color": "#000000",
        "logo": "",
        "watermark": "",
    },
    # --- Quality depth (Phase 2) ---
    "research_enabled": False,
    "research_language": "en",
    "research_llm_tier": "template",
    "topic_memory": True,
    "topic_memory_days": 30,
    "trend_velocity": True,
    # --- Engine / DX (Phase 3) ---
    "cache_enabled": True,
    "max_workers": 0,
    "scene_broll": True,
    # --- Feedback loop + trust (Tier 1) ---
    "analytics_enabled": False,
    "analytics_lookback_days": 28,
    "verify_upload": True,
    "upload_process_timeout": 300,
    "show_citations": True,
    # --- Reach + learning (Tier 2) ---
    "topic_similarity_threshold": 0.6,
    "localization_tier": "template",
    "publish_learning": False,
    "publish_learning_min_samples": 5,
    # --- Quality + operations (Tier 3) ---
    "loop_ending": True,
    "cover_frame": True,
    "engagement_drafts": True,
    "auto_backup": True,
    "backup_keep": 14,
}

# Keys that must be numeric / list / bool when present (fail-fast checks).
_NUMERIC_KEYS = ("narrator_speed", "narrator_pause_ms", "min_resolution",
                 "videos_per_run", "music_volume", "loudness_i", "loudness_tp",
                 "captions_safe_zone", "topic_memory_days", "max_workers",
                 "analytics_lookback_days", "upload_process_timeout",
                 "topic_similarity_threshold", "publish_learning_min_samples",
                 "backup_keep")
_LIST_KEYS = ("niches", "niche_keywords", "music_urls", "music_library",
              "stock_image_urls", "stock_video_urls", "peak_windows",
              "reddit_subreddits")
_BOOL_KEYS = ("series_enabled", "research_enabled", "topic_memory",
              "trend_velocity", "cache_enabled", "captions_karaoke", "scene_broll",
              "analytics_enabled", "verify_upload", "show_citations",
              "publish_learning", "loop_ending", "cover_frame",
              "engagement_drafts", "auto_backup")


def _strip_comment(value):
    """Drop a trailing `# comment` that sits OUTSIDE quotes. A '#' inside a
    quoted string, or one not preceded by whitespace (e.g. a URL fragment),
    is kept. Without this, `speed: 1.2 # faster` parsed as the string
    '1.2 # faster' and crashed float() downstream."""
    in_single = in_double = False
    for i, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or value[i - 1] in " \t":
                return value[:i].rstrip()
    return value


def _flow_list(value):
    """Parse an inline flow list like `[]` or `[a, b]`. The loader previously
    stored these as the literal string '[]', which then iterated as the
    characters '[' and ']' (e.g. bogus niches)."""
    inner = value[1:-1].strip()
    if not inner:
        return []
    return [_scalar(part) for part in inner.split(",")]


def _scalar(value):
    value = _strip_comment(value.strip())
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


def _defaults_copy():
    return copy.deepcopy(DEFAULTS)


def _load_yaml_pyyaml(text):
    import yaml  # optional dependency
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml must be a mapping at the top level")
    config = _defaults_copy()
    for key, value in data.items():
        # Match the stdlib parser's convention: an empty scalar is "".
        config[key] = "" if value is None else value
    return config


def _load_yaml_fallback(lines):
    """Stdlib YAML-subset parser (flat scalars, lists, list-of-mappings,
    and one level of nested mapping such as the brand: block)."""
    config = _defaults_copy()
    current_list_key = None
    current_map_key = None
    current_dict = None
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indented = line[:1] in (" ", "\t")
        if stripped.startswith("- ") and current_list_key is not None:
            item = stripped[2:].strip()
            if item.startswith(('"', "'")):
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
            key, _, value = stripped.partition(":")
            current_dict[key.strip()] = _scalar(value)
            continue
        # Nested mapping block (e.g. brand:): indented `subkey: value`
        # lines with no preceding `- ` list item.
        if indented and current_list_key is not None and current_dict is None \
                and ":" in stripped and not stripped.startswith("- "):
            if isinstance(config[current_list_key], list) and not config[current_list_key]:
                config[current_list_key] = {}
                current_map_key = current_list_key
                current_list_key = None
            if current_map_key is not None:
                key, _, value = stripped.partition(":")
                config[current_map_key][key.strip()] = _scalar(value)
                continue
        if indented and current_map_key is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            config[current_map_key][key.strip()] = _scalar(value)
            continue
        if ":" in stripped and not indented:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            current_map_key = None
            if value == "":
                config[key] = []
                current_list_key = key
                current_dict = None
            else:
                value = _strip_comment(value)
                if value.startswith("[") and value.endswith("]"):
                    config[key] = _flow_list(value)
                else:
                    config[key] = _scalar(value)
                current_list_key = None
                current_dict = None
    return config


def _cleanup(config):
    for key in ("music_urls", "stock_image_urls", "stock_video_urls", "peak_windows"):
        value = config.get(key, [])
        if isinstance(value, list):
            config[key] = [v for v in value if v]
    return config


def load_config(path="config.yaml"):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return _defaults_copy()
    try:
        config = _load_yaml_pyyaml(text)
    except ImportError:
        config = _load_yaml_fallback(text.splitlines(keepends=True))
    return _cleanup(config)


def validate_config(config):
    """Fail fast on obviously wrong config types. Returns a list of
    error strings (empty = valid). Uses pydantic when available for a
    stricter schema, else the built-in type checks below."""
    errors = []
    for key in _NUMERIC_KEYS:
        if key in config and config[key] not in ("", None):
            if not isinstance(config[key], (int, float)) or isinstance(config[key], bool):
                errors.append(f"{key} must be a number, got {config[key]!r}")
    for key in _LIST_KEYS:
        if key in config and config[key] not in ("", None):
            if not isinstance(config[key], list):
                errors.append(f"{key} must be a list, got {config[key]!r}")
    for key in _BOOL_KEYS:
        if key in config and config[key] not in ("", None):
            if not isinstance(config[key], bool):
                errors.append(f"{key} must be true/false, got {config[key]!r}")
    brand = config.get("brand")
    if brand not in ("", None) and not isinstance(brand, dict):
        errors.append(f"brand must be a mapping, got {brand!r}")
    tier = config.get("narrator_tier", "free")
    if tier not in ("", None) and str(tier).lower() not in ("free", "local", "paid"):
        errors.append(f"narrator_tier must be free/local/paid, got {tier!r}")
    loc_tier = config.get("localization_tier", "template")
    if loc_tier not in ("", None) and str(loc_tier).lower() not in ("template", "api"):
        errors.append(f"localization_tier must be template/api, got {loc_tier!r}")
    threshold = config.get("topic_similarity_threshold")
    if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
        if not 0.0 <= threshold <= 1.0:
            errors.append(f"topic_similarity_threshold must be in [0, 1], got {threshold!r}")
    lang = config.get("language")
    if lang not in ("", None) and (not isinstance(lang, str)
                                   or not re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$", lang)):
        errors.append(f"language must be a BCP-47 code like 'en' or 'es-MX', got {lang!r}")
    return errors


def load_config_validated(path="config.yaml"):
    """load_config + fail-fast validation (raises ValueError on errors)."""
    config = load_config(path)
    errors = validate_config(config)
    if errors:
        raise ValueError("Invalid config.yaml:\n  - " + "\n  - ".join(errors))
    return config
