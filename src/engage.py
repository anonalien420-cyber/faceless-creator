"""End-screen + community engagement drafts (Tier 3, human-reviewed).

YouTube's Data API cannot set end-screen elements or publish community
posts — those are Studio-only actions. So this module automates the
prep, not the posting: after a run it writes ready-to-paste drafts
(data/engagement_drafts.json + .md) with exact end-screen timings and
community-post/pinned-comment text built from the script's own verified
content. A human reviews and pastes them in YouTube Studio.

Nothing here posts anything, and nothing uses an LLM: drafts are
template-built from the script (hook, open question, verified sources),
so they inherit the accuracy guardrails — no invented claims.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone


def end_screen_plan(duration, fmt="long", has_playlist=False):
    """End-screen element plan for the LAST 20 seconds (YouTube's max
    end-screen window). Shorts have no end screens — return None.

    Returns {window_start, window_end, elements: [...]} with Studio
    placement hints. Subscribe + one video element is the reliable
    two-element layout; a playlist replaces the video when available."""
    if fmt != "long" or not duration or duration < 25:
        return None
    start = max(0.0, duration - 20.0)
    second = ("playlist" if has_playlist else "video")
    return {
        "window_start": round(start, 2),
        "window_end": round(duration, 2),
        "elements": [
            {"type": "subscribe", "placement": "left",
             "note": "Channel icon, left third; keep clear of captions."},
            {"type": second, "placement": "right",
             "note": ("Most recent playlist of this series." if has_playlist
                      else "Next episode / best related video (choose in Studio).")},
        ],
        "how_to": "YouTube Studio -> video -> Editor -> End screen. "
                  "Add the elements above inside the window; the API cannot set them.",
    }


def community_draft(script, video_id="", fmt="long"):
    """A community post draft tied to the video's own open question.
    Template-built from the script — no LLM, no invented claims."""
    topic = (script.get("topic") or "this story").strip()
    hook = (script.get("hook") or "").split(". ")[0].strip()
    question = script.get("cta") or "What do you think happened?"
    url = f"https://youtu.be/{video_id}" if video_id else "(paste the video link)"
    lines = []
    if hook:
        lines.append(hook)
    lines.append(f"New {'video' if fmt == 'long' else 'Short'}: {topic}.")
    lines.append(url)
    lines.append("")
    lines.append(f"Poll: {question}")
    lines.append("  Option A: The conventional explanation holds up.")
    lines.append("  Option B: Something is still missing from the record.")
    lines.append("  Option C: Tell me your theory in the comments.")
    return {
        "type": "community_poll",
        "text": "\n".join(lines),
        "status": "draft — human review required; post manually in Studio",
    }


def pinned_comment_draft(script, video_id=""):
    """Pinned comment: the open question + verified sources, so the
    comment section starts from evidence, not speculation."""
    question = script.get("cta") or "What do you think happened?"
    sources = []
    for entry in script.get("sources") or []:
        if isinstance(entry, dict):
            title = (entry.get("title") or "").strip()
            url = (entry.get("url") or "").strip()
            if title and url and url.startswith("http"):
                sources.append(f"{title}: {url}")
        elif isinstance(entry, str) and entry.startswith("http"):
            sources.append(entry)
    text = question + "\n\nSources:\n" + "\n".join(sources[:4]) if sources else question
    return {
        "type": "pinned_comment",
        "text": text,
        "status": "draft — human review required; pin manually in Studio",
    }


def build_drafts(outputs, seo_entries=None, feedback=None, feedback_path="data/upload_feedback.json"):
    """One draft bundle per output. `outputs` items: {script, format,
    duration?}; video_id is merged from upload feedback when present."""
    by_topic = {}
    if feedback is None and os.path.exists(feedback_path):
        try:
            with open(feedback_path, encoding="utf-8") as fh:
                feedback = json.load(fh)
        except (OSError, ValueError):
            feedback = []
    for entry in feedback or []:
        if entry.get("topic"):
            by_topic[entry["topic"]] = entry.get("video_id", "")
    bundles = []
    for item in outputs:
        script = item.get("script") or {}
        fmt = item.get("format", "long")
        video_id = item.get("video_id") or by_topic.get(script.get("topic", ""), "")
        duration = float(item.get("duration") or 0)
        bundles.append({
            "topic": script.get("topic", ""),
            "format": fmt,
            "video_id": video_id,
            "end_screen": end_screen_plan(duration, fmt),
            "community_post": community_draft(script, video_id=video_id, fmt=fmt),
            "pinned_comment": pinned_comment_draft(script, video_id=video_id),
        })
    return bundles


def write_drafts(outputs, path="data/engagement_drafts.json", **kwargs):
    bundles = build_drafts(outputs, **kwargs)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(),
               "note": "DRAFTS ONLY — nothing is auto-posted. Review, then "
                       "paste in YouTube Studio (end screens/community posts "
                       "have no public API).",
               "drafts": bundles}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    md_path = os.path.splitext(path)[0] + ".md"
    lines = ["# Engagement drafts (human review required)", ""]
    for bundle in bundles:
        lines.append(f"## {bundle['topic']} ({bundle['format']})")
        if bundle["video_id"]:
            lines.append(f"Video: https://youtu.be/{bundle['video_id']}")
        plan = bundle["end_screen"]
        if plan:
            lines.append(f"\nEnd screen ({plan['window_start']}s–{plan['window_end']}s):")
            for element in plan["elements"]:
                lines.append(f"- {element['type']} ({element['placement']}): {element['note']}")
        else:
            lines.append("\nEnd screen: not applicable (Shorts / too short).")
        lines.append("\nCommunity post draft:\n")
        lines.append("```\n" + bundle["community_post"]["text"] + "\n```")
        lines.append("\nPinned comment draft:\n")
        lines.append("```\n" + bundle["pinned_comment"]["text"] + "\n```")
        lines.append("")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="End-screen + community drafts (never auto-posts).")
    parser.add_argument("--scripts", default="data/scripts_long.json")
    parser.add_argument("--format", default="long", choices=["short", "long"])
    parser.add_argument("--output", default="data/engagement_drafts.json")
    args = parser.parse_args(argv)
    if not os.path.exists(args.scripts):
        print(f"ERROR: {args.scripts} not found — run the script stage first.")
        return 1
    with open(args.scripts, encoding="utf-8") as fh:
        scripts = json.load(fh)
    outputs = [{"script": s, "format": args.format,
                "duration": s.get("estimated_seconds") or (600 if args.format == "long" else 55)}
               for s in scripts]
    path = write_drafts(outputs, args.output)
    print(f"Engagement drafts -> {path} (+ .md). Review, then paste in YouTube Studio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
