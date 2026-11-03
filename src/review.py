"""Weekly self-review: learn from the channel's own last 7 days, then
correct the pipeline — within safe bounds only.

Inputs (real numbers only, never invented):
- YouTube Data API, when token.json + client_secrets.json exist and the
  channel can be read: views, likes, comments per recent video.
  Retention/average-view-duration needs the Analytics API and is NOT
  fetched here; those fields stay null unless the manual file provides
  them.
- Otherwise (the normal case): a manual stats file
  data/video_stats.json, pasted from YouTube Studio by the creator.
  Format: list of {video_id, title, niche, hook_style, length_seconds,
  music_genre, music_tempo_bpm, music_mood, publish_time (ISO),
  views, avg_view_duration_seconds, retention_pct, likes, comments,
  published_date}. See data/video_stats.example.json (EXAMPLE only).
- Videos with no stats are listed as "no data yet" and are NOT scored.

Outputs: data/weekly_review.md + data/weekly_review.json, and
data/review_history.json (before/after, for reversibility).

Auto-corrections (SAFE BOUNDS ONLY, applied to config.yaml, logged):
- Niche: +20 demand bonus for the winning niche in the next ranking
  (config review_preferred_niche). It nudges ranking, it does not
  delete or ban any niche.
- Hook style: set review_preferred_hook_style to the top performers'
  most common hook style (script.py uses it next run).
- Length: set review_preferred_length_seconds to the top performers'
  median length, clamped to 30-60s for Shorts.
- Music: set review_music_genre/tempo/mood to the top performers'
  profile (music.py overrides the trending profile with these).
- Peak window: shift peak windows by at most 60 minutes toward the
  winning publish hours (config review_peak_shift_minutes, clamped
  to [-60, +60]; scheduler.py applies it).

NEVER (this module does not do any of these, by design):
- Delete videos, change a video's privacy after publishing, change
  channel settings, or spend money. Anything bigger than the bounds
  above goes into weekly_review.md as a RECOMMENDATION for the human,
  not an auto-change.
"""

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone

try:
    from src.config import load_config
except ImportError:
    from config import load_config

REVIEW_KEYS = ("review_preferred_niche", "review_preferred_hook_style",
               "review_preferred_length_seconds", "review_music_genre",
               "review_music_tempo_bpm", "review_music_mood",
               "review_peak_shift_minutes")


def _median(values, default=None):
    values = [v for v in values if isinstance(v, (int, float))]
    return statistics.median(values) if values else default


def _mode(values, default=""):
    values = [v for v in values if v]
    if not values:
        return default
    return max(set(values), key=values.count)


def load_manual_stats(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    return data.get("videos", data.get("stats", []))


def load_youtube_stats():
    """Best-effort YouTube Data API read (views/likes/comments only).

    Returns [] unless token.json + client_secrets.json exist and the
    API call succeeds. Retention is NOT available from the Data API,
    so it stays null here. Any failure falls back to manual stats.
    """
    if not (os.path.exists("token.json") and os.path.exists("client_secrets.json")):
        return []
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        scopes = ["https://www.googleapis.com/auth/youtube.readonly"]
        creds = Credentials.from_authorized_user_file("token.json", scopes)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        youtube = build("youtube", "v3", credentials=creds)
        channels = youtube.channels().list(part="contentDetails", mine=True).execute()
        items = channels.get("items", [])
        if not items:
            return []
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        playlist = youtube.playlistItems().list(
            part="snippet,contentDetails", playlistId=uploads, maxResults=50).execute()
        ids = [i["contentDetails"]["videoId"] for i in playlist.get("items", [])]
        if not ids:
            return []
        videos = youtube.videos().list(
            part="snippet,statistics,contentDetails", id=",".join(ids)).execute()
        out = []
        for item in videos.get("items", []):
            stats = item.get("statistics", {})
            out.append({
                "video_id": item["id"],
                "title": item["snippet"].get("title", ""),
                "published_date": item["snippet"].get("publishedAt", ""),
                "views": int(stats["viewCount"]) if "viewCount" in stats else None,
                "likes": int(stats["likeCount"]) if "likeCount" in stats else None,
                "comments": int(stats["commentCount"]) if "commentCount" in stats else None,
                "niche": "", "hook_style": "", "length_seconds": None,
                "music_genre": "", "music_tempo_bpm": None, "music_mood": "",
                "publish_time": item["snippet"].get("publishedAt", ""),
                "avg_view_duration_seconds": None, "retention_pct": None,
                "source": "youtube_data_api",
            })
        return out
    except Exception as exc:
        print(f"WARNING: YouTube stats read failed ({exc}); using manual stats.",
              file=sys.stderr)
        return []


def last_7_days(videos):
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent, older = [], []
    for video in videos:
        raw = video.get("published_date") or video.get("publish_time") or ""
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            dt = None
        (recent if (dt is None or dt >= cutoff) else older).append(video)
    return recent, older


def analyse(videos):
    """Split into scored / no-data, top / bottom, and shared traits."""
    scored = [v for v in videos if isinstance(v.get("views"), (int, float))]
    no_data = [v for v in videos if not isinstance(v.get("views"), (int, float))]
    scored.sort(key=lambda v: v["views"], reverse=True)
    top = scored[:3] if len(scored) >= 3 else scored
    bottom = scored[-3:] if len(scored) >= 3 else []
    median_views = _median([v["views"] for v in scored])
    shared = {}
    if top:
        shared = {
            "niche": _mode([v.get("niche") for v in top]),
            "hook_style": _mode([v.get("hook_style") for v in top]),
            "length_seconds": _median([v.get("length_seconds") for v in top]),
            "music_genre": _mode([v.get("music_genre") for v in top]),
            "music_tempo_bpm": _median([v.get("music_tempo_bpm") for v in top]),
            "music_mood": _mode([v.get("music_mood") for v in top]),
            "publish_hours": [v.get("publish_time", "")[11:13] for v in top
                              if v.get("publish_time")],
        }
    return scored, no_data, top, bottom, median_views, shared


def hypotheses(bottom, median_views, shared):
    """Likely causes, explicitly labelled hypotheses — never facts."""
    out = []
    for video in bottom:
        views = video.get("views") or 0
        retention = video.get("retention_pct")
        length = video.get("length_seconds")
        title = video.get("title", "untitled")
        if retention is not None and retention < 30:
            out.append(f"{title}: HYPOTHESIS — retention {retention}% is low, "
                       "so the hook may not be landing in the first 3 seconds.")
        if median_views and views < 0.5 * median_views and length and shared.get("length_seconds") \
                and length > shared["length_seconds"] + 20:
            out.append(f"{title}: HYPOTHESIS — longer than top performers "
                       f"({length}s vs median {shared['length_seconds']}s) with "
                       "well below-median views; length may be hurting it.")
        if not out or title not in " ".join(out):
            out.append(f"{title}: HYPOTHESIS — below top performers; cause "
                       "not established from views alone (topic, hook, "
                       "timing, or thumbnail could all matter).")
    return out


def clamp(value, low, high):
    return max(low, min(high, value))


def apply_adjustments(config_path, shared, top):
    """Write safe-bounded adjustments into config.yaml, return before/after."""
    config = load_config(config_path)
    before = {key: config.get(key, "") for key in REVIEW_KEYS}
    after = dict(before)
    if not top:
        return before, after, []
    if shared.get("niche"):
        after["review_preferred_niche"] = shared["niche"]
    if shared.get("hook_style"):
        after["review_preferred_hook_style"] = shared["hook_style"]
    if shared.get("length_seconds") is not None:
        after["review_preferred_length_seconds"] = int(
            clamp(round(shared["length_seconds"]), 30, 60))
    if shared.get("music_genre"):
        after["review_music_genre"] = shared["music_genre"]
    if shared.get("music_tempo_bpm") is not None:
        after["review_music_tempo_bpm"] = int(shared["music_tempo_bpm"])
    if shared.get("music_mood"):
        after["review_music_mood"] = shared["music_mood"]
    # Peak shift: median winning publish hour vs default 18:00 weekday
    # peak, clamped to +/-60 minutes. Only if publish hours are known.
    hours = []
    for hour in shared.get("publish_hours", []):
        try:
            hours.append(int(hour))
        except ValueError:
            pass
    if hours:
        shift = int(clamp(round((statistics.median(hours) - 18) * 60), -60, 60))
        after["review_peak_shift_minutes"] = shift
    else:
        shift = 0
    # Rewrite config.yaml: replace existing review_* lines, append the rest.
    with open(config_path, encoding="utf-8") as fh:
        lines = fh.readlines()
    kept = [ln for ln in lines
            if not any(ln.startswith(key + ":") for key in REVIEW_KEYS)]
    if kept and not kept[-1].endswith("\n"):
        kept[-1] += "\n"
    kept.append("\n# --- Auto-review adjustments (written by src/review.py) ---\n")
    kept.append("# Reversible: see data/review_history.json before/after values.\n")
    for key in REVIEW_KEYS:
        value = after[key]
        if value == "" or value is None:
            continue
        kept.append(f"{key}: {value}\n")
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.writelines(kept)
    applied = [f"{k}: {before[k]!r} -> {after[k]!r}"
               for k in REVIEW_KEYS if before[k] != after[k]]
    return before, after, applied


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", default="data/video_stats.json")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", default="data/weekly_review.md")
    parser.add_argument("--json-output", default="data/weekly_review.json")
    parser.add_argument("--history", default="data/review_history.json")
    args = parser.parse_args(argv)

    videos = load_youtube_stats() or load_manual_stats(args.stats)
    recent, older = last_7_days(videos)
    pool = recent if recent else videos
    scored, no_data, top, bottom, median_views, shared = analyse(pool)
    hyps = hypotheses(bottom, median_views, shared)
    recommendations = []
    if not scored:
        recommendations.append(
            "No performance data at all this week — add data/video_stats.json "
            "from YouTube Studio (or connect YouTube OAuth) before trusting "
            "any ranking. No auto-changes were made.")
    if top and len({v.get("niche") for v in top if v.get("niche")}) == 1:
        recommendations.append(
            "Top performers are all in one niche — consider (human decision, "
            "not auto-applied) leaning into that niche, but do not drop other "
            "niches on one week's data alone.")
    recommendations.append(
        "Anything bigger than the safe bounds (dropping a niche, changing "
        "format to long-form, spending on promotion) is a human decision — "
        "it is listed here, never auto-applied.")

    before, after, applied = (({}, {}, [])
                              if not scored else apply_adjustments(args.config, shared, top))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "videos_considered": len(pool),
        "scored": len(scored),
        "no_data": [v.get("title", v.get("video_id", "")) for v in no_data],
        "top_performers": top,
        "bottom_performers": bottom,
        "shared_top_traits": shared,
        "median_views": median_views,
        "hypotheses": hyps,
        "adjustments_applied": applied,
        "recommendations": recommendations,
    }
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.json_output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    lines = ["# Weekly self-review", "",
             f"Videos considered (last 7 days, or all if none recent): {len(pool)}; "
             f"scored: {len(scored)}; no data yet: {len(no_data)}.", "",
             "## What's popular"]
    for video in top:
        lines.append(f"- {video.get('title', '')} — {video.get('views')} views"
                     + (f", retention {video.get('retention_pct')}%" if video.get("retention_pct") is not None else "")
                     + f" (niche: {video.get('niche') or 'unknown'}, "
                       f"hook: {video.get('hook_style') or 'unknown'}, "
                       f"length: {video.get('length_seconds') or '?'}s)")
    if shared:
        lines.append("")
        lines.append("What top performers share: "
                     f"niche {shared.get('niche') or 'mixed'}, "
                     f"hook style {shared.get('hook_style') or 'mixed'}, "
                     f"median length {shared.get('length_seconds')}s, "
                     f"music {shared.get('music_genre') or 'mixed'}/"
                     f"{shared.get('music_tempo_bpm') or '?'} BPM/"
                     f"{shared.get('music_mood') or 'mixed'}.")
    lines.append("")
    lines.append("## What's not working (hypotheses, not facts)")
    for hyp in hyps:
        lines.append(f"- {hyp}")
    if no_data:
        lines.append("")
        lines.append("No data yet (not scored, not failures):")
        for title in report["no_data"]:
            lines.append(f"- {title}")
    lines.append("")
    lines.append("## Auto-corrections applied (safe bounds only)")
    for item in applied:
        lines.append(f"- {item}")
    if not applied:
        lines.append("- None (no scored data, or top traits already matched config).")
    lines.append("")
    lines.append("## Recommendations for you (NOT auto-applied)")
    for rec in recommendations:
        lines.append(f"- {rec}")
    lines.append("")
    lines.append("Never auto-done by this review: deleting videos, changing a "
                 "video's privacy after publishing, changing channel settings, "
                 "or spending money.")
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    # History (reversibility): append before/after for this week.
    history = []
    if os.path.exists(args.history):
        with open(args.history, encoding="utf-8") as fh:
            history = json.load(fh)
    history.append({"date": report["generated_at"], "before": before,
                    "after": after, "adjustments": applied,
                    "top_traits": shared})
    with open(args.history, "w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=2)
    print(f"Weekly review -> {args.output} ({len(scored)} scored, "
          f"{len(applied)} adjustments applied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
