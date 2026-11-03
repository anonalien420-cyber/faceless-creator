"""SEO per video: original titles, description, tags, pinned comment.

Output: data/seo.json per run — one entry per video.

Rules:
- Titles are ORIGINAL: generated from the video's own topic + hook
  style, never copied from a trending video's title. Three options per
  video, ranked, with one recommended title.
- Long-form titles stay under 60 characters (YouTube truncates longer
  titles in search); Shorts titles stay punchy and short.
- Description: hook + chapters/timestamps for longs (timestamps are
  filled in by run.py from narration length; seo.json lists chapter
  titles) + CTA + channel promise (from config, if set).
- Tags come from the trending keywords (config niche_keywords) + the
  topic's own content words — never from another creator's tag list.
- Pinned comment is a question that invites replies (engagement
  without clickbait or fake claims).
- Series: with --series-name and --episode, the recommended title is
  prefixed "SERIES EP N: " (episode numbering lives in
  data/series_state.json, incremented only after a successful render).
- History videos: the description carries a "Sources you can check"
  section (public, checkable sources only: museums, universities,
  archives, peer-reviewed publications, reputable encyclopedias,
  official records), plus the next-episode tease and viewer question.
  A source with no public URL is listed as "no public URL —
  available on request / see review queue" and flagged in the
  entry's `sources` list. A URL is NEVER invented: if no URL is
  known, the entry says so instead of guessing one.
"""

import argparse
import json
import os
import re

try:
    from src.config import load_config
except ImportError:
    from config import load_config

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "how",
    "why", "what", "best", "top", "you", "your", "with", "that", "this",
}


def _title_case(topic):
    return topic.strip().title()


def _under_60(text):
    return text if len(text) <= 60 else ""


def long_titles(topic, hook_style):
    base = _title_case(topic)
    candidates = [
        f"{base}: The Simple System That Works",
        f"{base} — Stop Starting Over",
        f"Why {base} Feels Hard (And the Fix)",
        f"{base}: One Small Win a Day",
    ]
    if hook_style == "question":
        candidates.insert(0, f"Is {base} Simpler Than You Think?")
    if hook_style == "shock":
        candidates.insert(0, f"You're Doing {base} Backwards")
    if hook_style == "story":
        candidates.insert(0, f"I Got {base} Wrong for Years")
    # Keep only titles under 60 chars; fall back to the bare topic.
    kept = [t for t in candidates if _under_60(t)]
    if not kept:
        kept = [base[:60]]
    return kept[:3]


def short_titles(topic, hook_style):
    base = _title_case(topic)
    candidates = [
        f"{base} in 60 Seconds",
        f"Stop Doing {base} Wrong",
        f"The {base} Fix Nobody Tells You",
        f"{base}: Try This Today",
    ]
    if hook_style == "question":
        candidates.insert(0, f"Is {base} This Simple?")
    return candidates[:3]


def normalize_sources(sources):
    """Normalize script sources to [{title, url, no_public_url}].

    Accepts dicts ({title, url} or {title, no_public_url: true}) and
    plain strings. A plain string starting with http is used as its
    own URL; any other string is a title with NO public URL and is
    flagged as such — a URL is never invented for it. Placeholder
    entries are dropped entirely (they must never reach a description).
    """
    normalized = []
    for entry in sources or []:
        if isinstance(entry, dict):
            title = (entry.get("title") or "").strip()
            url = (entry.get("url") or "").strip() or None
            if not title and not url:
                continue
            normalized.append({
                "title": title or url,
                "url": url,
                "no_public_url": bool(entry.get("no_public_url")) or url is None,
            })
        else:
            text = str(entry).strip()
            if not text or any(m.lower() in text.lower()
                               for m in ("do NOT publish", "placeholder")):
                continue
            if text.startswith("http"):
                normalized.append({"title": text, "url": text,
                                   "no_public_url": False})
            else:
                normalized.append({"title": text, "url": None,
                                   "no_public_url": True})
    return normalized


def format_sources_section(sources):
    """Render the viewer-facing 'Sources you can check' section."""
    lines = ["Sources you can check:"]
    for src in sources:
        if src["url"]:
            lines.append(f"- {src['title']} — {src['url']}")
        else:
            lines.append(f"- {src['title']} — no public URL "
                         "(available on request / see review queue)")
    return "\n".join(lines)


def tags_for(topic, config):
    tags = []
    for keyword in config.get("niche_keywords") or []:
        if keyword and keyword not in tags:
            tags.append(keyword)
    for word in re.findall(r"[a-zA-Z']+", topic.lower()):
        if word not in STOPWORDS and word not in tags and len(word) > 2:
            tags.append(word)
    return tags[:15]


def build_entry(script, config, fmt, series_name="", episode=None, thumbnails=None):
    topic = script["topic"]
    hook_style = script.get("hook_style", "statement")
    titles = long_titles(topic, hook_style) if fmt == "long" else short_titles(topic, hook_style)
    recommended = titles[0]
    if series_name and episode is not None:
        prefix = f"{series_name} EP {episode}: "
        if len(prefix + recommended) <= 60 or fmt == "short":
            recommended = prefix + recommended
        titles = [recommended] + [t for t in titles if t != recommended][:2]
    hook = script.get("hook", "")
    chapters = script.get("chapters", []) if fmt == "long" else []
    # Description here is hook + CTA + channel promise. Timestamped
    # chapters are prepended at upload time by run.py (which knows the
    # narration length), so they are not duplicated here.
    description_parts = [hook, script.get("cta", "")]
    promise = config.get("channel_promise", "")
    if promise and "YOUR_" not in promise:
        description_parts.append(promise)
    sources = []
    if script.get("style") == "history_mystery":
        pinned_comment = (
            "What do you think happened? Share your theory below — "
            "speculation is welcome here, and it stays speculation until "
            "evidence proves otherwise. What evidence would change your mind?")
        # Viewer-facing sources: only real, normalized sources reach
        # the description, and the shock hook's source is included too
        # (it is the first claim viewers will want to check).
        sources = normalize_sources(script.get("sources"))
        shock = script.get("shock_hook") or {}
        shock_source = shock.get("source") or {}
        if shock_source and not any(
                s["title"] == shock_source.get("title")
                and s["url"] == shock_source.get("url") for s in sources):
            sources = [normalize_sources([shock_source])[0]] + sources \
                if normalize_sources([shock_source]) else sources
        if sources:
            description_parts.append(format_sources_section(sources))
        if script.get("next_episode_tease"):
            description_parts.append(script["next_episode_tease"])
        description_parts.append(
            "What do you think happened? Share your theory in the comments.")
    else:
        pinned_comment = (
            f"Quick question: which small win from this video are you picking "
            f"first for {topic}? Reply below — I read every comment.")
    return {
        "format": fmt,
        "topic": topic,
        "titles": titles,
        "recommended_title": recommended,
        "description": "\n\n".join(p for p in description_parts if p),
        "chapters": chapters,
        "tags": tags_for(topic, config),
        "thumbnails": thumbnails or [],
        "pinned_comment": pinned_comment,
        "sources": sources,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--long", default="data/scripts_long.json")
    parser.add_argument("--short", default="data/scripts_shorts.json")
    parser.add_argument("--output", default="data/seo.json")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--series-name", default="")
    parser.add_argument("--episode", type=int, default=0,
                        help="Episode number for this day's series entry (0 = no prefix).")
    parser.add_argument("--thumbnails-file", default="",
                        help="JSON mapping topic -> thumbnail variant list (from run.py).")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    thumb_map = {}
    if args.thumbnails_file and os.path.exists(args.thumbnails_file):
        with open(args.thumbnails_file, encoding="utf-8") as fh:
            thumb_map = json.load(fh)
    entries = []
    for fmt, path in (("long", args.long), ("short", args.short)):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            scripts = json.load(fh)
        for script in scripts:
            entries.append(build_entry(
                script, config, fmt,
                series_name=args.series_name,
                episode=args.episode if args.episode else None,
                thumbnails=thumb_map.get(script["topic"], [])))
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
    for entry in entries:
        print(f"[{entry['format']}] {entry['topic']} -> recommended: "
              f"{entry['recommended_title']!r} (tags: {', '.join(entry['tags'][:5])})")
    print(f"Wrote {len(entries)} SEO entries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
