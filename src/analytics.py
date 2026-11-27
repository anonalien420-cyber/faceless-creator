"""Retention analytics loop — the metric that actually decides Shorts.

review.py reads views/likes/comments from the YouTube Data API, but the
Data API does NOT expose retention. This module pulls retention from the
YouTube **Analytics API** (averageViewDuration, averageViewPercentage,
estimatedMinutesWatched) so the weekly review's hook/length/pacing
corrections are driven by how long people actually watch — not just how
many clicked.

Opt-in and $0: the Analytics API is free. It needs an OAuth token that
includes the `youtube-analytics.readonly` scope (re-consent once, or add
the scope to your token). Without a valid token, or on any API failure,
this returns nothing and review.py falls back to manual/Data-API stats —
the pipeline never breaks because analytics is unavailable.

Config: analytics_enabled (default false), analytics_lookback_days.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

ANALYTICS_SCOPE = "https://www.googleapis.com/auth/youtube-analytics.readonly"

# Analytics metric -> the stats field review.py already understands.
_METRIC_FIELDS = {
    "averageViewDuration": "avg_view_duration_seconds",
    "averageViewPercentage": "retention_pct",
    "estimatedMinutesWatched": "estimated_minutes_watched",
    "views": "views",
}


def parse_retention_report(report):
    """Turn an Analytics reports.query response into per-video stats.

    Pure function (unit-testable). The response has columnHeaders (names)
    and rows (values). Each row becomes a dict keyed by video_id with the
    retention fields review.py uses. averageViewPercentage is already a
    0-100 percentage; averageViewDuration is seconds.
    """
    if not report:
        return []
    headers = [h.get("name", "") for h in report.get("columnHeaders", [])]
    if "video" not in headers:
        return []
    out = []
    for row in report.get("rows", []):
        record = dict(zip(headers, row, strict=False))
        video_id = record.get("video")
        if not video_id:
            continue
        entry = {"video_id": video_id, "source": "youtube_analytics_api"}
        for metric, field in _METRIC_FIELDS.items():
            if metric in record and record[metric] is not None:
                entry[field] = record[metric]
        out.append(entry)
    return out


def _load_credentials():
    """Load an OAuth token with the analytics scope, or None."""
    if not os.path.exists("token.json"):
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file("token.json", [ANALYTICS_SCOPE])
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds if creds and creds.valid else None
    except Exception as exc:
        print(f"WARNING: analytics credentials unavailable ({exc}).", file=sys.stderr)
        return None


def fetch_retention(start_date, end_date, max_results=200):
    """Query the Analytics API for per-video retention. Returns [] on any
    failure (no token, missing scope, network/quota error)."""
    creds = _load_credentials()
    if creds is None:
        return []
    try:
        from googleapiclient.discovery import build
        analytics = build("youtubeAnalytics", "v2", credentials=creds)
        report = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date, endDate=end_date,
            metrics="averageViewDuration,averageViewPercentage,estimatedMinutesWatched,views",
            dimensions="video", sort="-views", maxResults=max_results,
        ).execute()
        return parse_retention_report(report)
    except Exception as exc:
        print(f"WARNING: Analytics API query failed ({exc}); "
              "falling back to manual/Data-API stats.", file=sys.stderr)
        return []


def enrich_with_retention(videos, config=None):
    """Fill retention fields on videos that have a video_id but no
    retention yet. No-op (returns videos unchanged) when analytics is
    disabled or unavailable. Never raises."""
    config = config or {}
    if not config.get("analytics_enabled", False):
        return videos
    if not any(v.get("video_id") for v in videos):
        return videos
    lookback = int(config.get("analytics_lookback_days", 28) or 28)
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=lookback)
    retention = fetch_retention(start.isoformat(), end.isoformat())
    if not retention:
        return videos
    by_id = {r["video_id"]: r for r in retention}
    for video in videos:
        match = by_id.get(video.get("video_id"))
        if not match:
            continue
        for field in ("avg_view_duration_seconds", "retention_pct",
                      "estimated_minutes_watched"):
            if video.get(field) is None and match.get(field) is not None:
                video[field] = match[field]
        video.setdefault("retention_source", "youtube_analytics_api")
    return videos
