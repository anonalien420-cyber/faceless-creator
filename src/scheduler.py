"""Pick the next YouTube publish window (peak time) for a niche.

Peak windows are GENERAL YouTube audience windows, NOT a guarantee of
popularity — timing helps, it does not make a video popular. Defaults
(config peak_windows, overridable per niche once you have your own
analytics):
- Weekdays (Mon-Fri): 17:00-20:00 local
- Weekends (Sat-Sun): 11:00-13:00 local
Local timezone comes from config channel_timezone (default
America/Chicago). Per-niche overrides use config entries of the form:
    "niche name:weekday:17:00-20:00"
    "niche name:weekend:12:00-14:00"
    "default:weekday:17:00-20:00"
    "default:weekend:11:00-13:00"
A niche entry wins over a default entry for the same day type.
upload.py uses this to set YouTube's publishAt: the video is uploaded
as private, then YouTube publishes it at the returned time.

No video is scheduled in the past: the returned window start is always
at least 15 minutes in the future (YouTube needs lead time for
processing), scanning up to 14 days ahead.
"""

import argparse
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    from src.config import load_config
except ImportError:
    from config import load_config

DEFAULT_WINDOWS = {
    ("default", "weekday"): [("17:00", "20:00")],
    ("default", "weekend"): [("11:00", "13:00")],
}


def _parse_hhmm(value):
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def parse_peak_windows(config):
    """Return {(niche_lower_or_default, day_type): [(start, end), ...]}."""
    windows = {key: list(value) for key, value in DEFAULT_WINDOWS.items()}
    seen_default = set()
    for entry in config.get("peak_windows") or []:
        if not isinstance(entry, str):
            continue
        parts = entry.split(":")
        # Format: "niche:weekday:17:00-20:00" — niche may itself contain
        # no colon in practice; split from the right for the window part.
        match = re.match(r"^(.+):(weekday|weekend):(\d{2}:\d{2})-(\d{2}:\d{2})$",
                         entry.strip())
        if not match:
            continue
        niche, day_type, start, end = match.groups()
        key = (niche.strip().lower(), day_type)
        if key[0] == "default" and key not in seen_default:
            # A config "default:" entry replaces the built-in default
            # (otherwise --list would show it twice); later entries append.
            windows[key] = [(start, end)]
            seen_default.add(key)
        else:
            # Append, don't overwrite: a scope may have several windows
            # per day type (e.g. Shorts midday AND evening); the first
            # window still ahead of "now" wins in next_peak_window().
            windows.setdefault(key, []).append((start, end))
    return windows


def windows_for_day(windows, niche, day, fmt=None):
    """Resolution order: niche window, then format window (shorts/long),
    then the default window. Format windows are config entries like
    "shorts:weekday:12:00-14:00" / "long:weekday:17:00-20:00"."""
    day_type = "weekend" if day.weekday() >= 5 else "weekday"
    niche_key = (niche or "").strip().lower()
    if niche_key and (niche_key, day_type) in windows:
        return windows[(niche_key, day_type)]
    # Config uses "shorts:" for the short-format window; code uses "short".
    fmt_scope = "shorts" if fmt == "short" else fmt
    if fmt_scope and (fmt_scope, day_type) in windows:
        return windows[(fmt_scope, day_type)]
    return windows.get(("default", day_type), [])


def next_peak_window(niche, config, now=None, fmt=None):
    """Return (window_start_local, window_end_local) datetimes, or (None, None).

    A weekly-review shift (config review_peak_shift_minutes, clamped to
    +/-60 by review.py) moves the window toward winning publish times.
    """
    tz_name = config.get("channel_timezone", "America/Chicago") or "America/Chicago"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    now = now.astimezone(tz)
    earliest = now + timedelta(minutes=15)
    windows = parse_peak_windows(config)
    try:
        shift = int(config.get("review_peak_shift_minutes") or 0)
    except (TypeError, ValueError):
        shift = 0
    shift = max(-60, min(60, shift))
    for day_offset in range(14):
        day = (now + timedelta(days=day_offset)).date()
        for start_s, end_s in windows_for_day(windows, niche, day, fmt=fmt):
            start = datetime.combine(day, _parse_hhmm(start_s), tzinfo=tz)
            end = datetime.combine(day, _parse_hhmm(end_s), tzinfo=tz)
            start = start + timedelta(minutes=shift)
            end = end + timedelta(minutes=shift)
            if start >= earliest:
                return start, end
    return None, None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", default="")
    parser.add_argument("--format", default="", choices=["", "short", "long"],
                        help="Use the format's peak window (shorts/long) if set.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--now", default="",
                        help="ISO timestamp for testing, e.g. 2026-11-03T10:00:00-06:00")
    parser.add_argument("--list", action="store_true", help="Print configured windows and stop.")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.list:
        windows = parse_peak_windows(config)
        for (niche, day_type), spans in sorted(windows.items()):
            print(f"{niche} {day_type}: {', '.join(f'{s}-{e}' for s, e in spans)}")
        print(f"Timezone: {config.get('channel_timezone', 'America/Chicago')}")
        return 0
    now = None
    if args.now:
        now = datetime.fromisoformat(args.now)
    start, end = next_peak_window(args.niche, config, now=now,
                                  fmt=args.format or None)
    if start is None:
        print("ERROR: No peak window found in the next 14 days.", file=__import__("sys").stderr)
        return 1
    print(f"Next peak window for niche '{args.niche or config.get('niche', '')}': "
          f"{start.isoformat()} to {end.isoformat()} "
          f"({start.strftime('%A %I:%M %p %Z')})")
    print(f"publishAt (UTC): {start.astimezone(timezone.utc).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
