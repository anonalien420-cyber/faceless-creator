"""Channel analytics import, metadata linting, and thumbnail experiment tracking."""
import argparse
import csv
import json
import os
from datetime import datetime, timezone


def lint_metadata(entry):
    errors, warnings = [], []
    title = (entry.get("recommended_title") or "").strip()
    description = (entry.get("description") or "").strip()
    tags = entry.get("tags") or []
    if not title:
        errors.append("missing title")
    if len(title) > 100:
        errors.append("title exceeds YouTube's 100-character limit")
    if len(title) > 70:
        warnings.append("title is long; check mobile truncation")
    if not description:
        errors.append("missing description")
    tag_chars = sum(len(str(tag)) for tag in tags)
    if tag_chars > 500:
        errors.append("combined tag text exceeds YouTube's 500-character limit")
    if entry.get("format") == "long" and not entry.get("chapters"):
        warnings.append("long-form entry has no chapter list")
    if entry.get("format") == "long" and "00:00" not in description:
        warnings.append("description does not contain timestamped chapters")
    return {"passed": not errors, "errors": errors, "warnings": warnings}


def _number(value):
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip().replace(",", "").replace("%", "")
    try:
        return float(raw)
    except ValueError:
        return None


def import_analytics_csv(path):
    """Import YouTube Studio CSV exports without inventing unavailable metrics."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            lowered = {str(k).strip().lower(): v for k, v in row.items()}
            title = lowered.get("video title") or lowered.get("content") or lowered.get("title") or ""
            video_id = lowered.get("video") or lowered.get("video id") or lowered.get("content id") or ""
            rows.append({
                "video_id": video_id, "title": title,
                "views": _number(lowered.get("views")),
                "impressions": _number(lowered.get("impressions")),
                "impressions_ctr_pct": _number(lowered.get("impressions click-through rate (%)")
                    or lowered.get("impressions click-through rate") or lowered.get("ctr")),
                "avg_view_duration": lowered.get("average view duration") or lowered.get("avg. view duration"),
                "average_percentage_viewed": _number(lowered.get("average percentage viewed (%)")
                    or lowered.get("average percentage viewed")),
                "watch_time_hours": _number(lowered.get("watch time (hours)")),
                "source": "youtube_studio_csv",
            })
    return rows


def compare_thumbnail_experiment(variants):
    """Compare variants only when exposure is adequate; no causal claims."""
    valid = [v for v in variants if isinstance(v.get("impressions"), (int, float))
             and isinstance(v.get("impressions_ctr_pct"), (int, float))]
    if len(valid) < 2:
        return {"status": "insufficient_data", "winner": None,
                "reason": "At least two variants need impressions and CTR."}
    valid.sort(key=lambda v: v["impressions_ctr_pct"], reverse=True)
    exposure = min(v["impressions"] for v in valid)
    if exposure < 100:
        return {"status": "insufficient_data", "winner": None,
                "reason": "Each variant needs at least 100 impressions before comparison."}
    return {"status": "directional_only", "winner": valid[0].get("variant"),
            "ranked": [{"variant": v.get("variant"), "impressions": v["impressions"],
                        "ctr_pct": v["impressions_ctr_pct"]} for v in valid],
            "warning": "Observational comparison only; audience, traffic source, and timing can confound results."}


def build_growth_report(analytics, metadata_entries=None):
    reports = []
    for entry in metadata_entries or []:
        reports.append({"topic": entry.get("topic"),
                        "lint": lint_metadata(entry)})
    scored = [r for r in analytics if isinstance(r.get("views"), (int, float))]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video_count": len(analytics), "videos_with_view_data": len(scored),
        "total_views": sum(r["views"] for r in scored),
        "average_views": (sum(r["views"] for r in scored) / len(scored)) if scored else None,
        "average_ctr_pct": (sum(r["impressions_ctr_pct"] for r in analytics
                               if isinstance(r.get("impressions_ctr_pct"), (int, float))) /
                            len([r for r in analytics if isinstance(r.get("impressions_ctr_pct"), (int, float))]))
                           if any(isinstance(r.get("impressions_ctr_pct"), (int, float)) for r in analytics) else None,
        "metadata": reports,
        "limitations": ["CSV metrics are only as complete as the export.",
                        "CTR and retention vary by traffic source and video age.",
                        "No automatic changes to channel settings or published videos are made."],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analytics-csv", required=True)
    parser.add_argument("--metadata-json", default="")
    parser.add_argument("--output", default="data/growth_report.json")
    args = parser.parse_args(argv)
    analytics = import_analytics_csv(args.analytics_csv)
    metadata = []
    if args.metadata_json and os.path.exists(args.metadata_json):
        with open(args.metadata_json, encoding="utf-8") as fh:
            metadata = json.load(fh)
    report = build_growth_report(analytics, metadata)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print("Growth report -> {} ({} video(s))".format(args.output, len(analytics)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
