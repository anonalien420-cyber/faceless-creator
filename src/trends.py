"""Find trending candidates across YouTube, Reddit, TikTok, Facebook,
and Google — and compare them. No fake numbers, ever.

What each source can actually do for free vs. what needs a key/token
(full table in README.md):
- YouTube: YouTube Data API v3 when YT_API_KEY is set; otherwise
  manual input only. Never scraped, never faked.
- Reddit: public subreddit search/hot JSON, no key needed, with a
  polite User-Agent. Scored by upvotes + comments + recency.
- TikTok: NO free official API without approval, and no scraping
  (that would break TikTok's terms). Supported: (a) TikTok Research
  API when TIKTOK_RESEARCH_TOKEN is set, (b) manual paste of trending
  TikTok URLs in trends_input.json. TikTok entries are always marked
  manual/API-only.
- Facebook: no public video search without a token. Supported:
  (a) Graph API when FACEBOOK_GRAPH_TOKEN is set, (b) manual paste.
  Marked manual/API-only.
- Google: Google Trends via pytrends if installed, otherwise the free
  Google Trends daily RSS feed. Used for demand/interest comparison,
  NOT for video views — Google entries always have engagement null.

Compare step: all sources are normalized into one table
(source, title/topic, url, engagement, recency, demand_signal),
deduplicated by normalized title/topic, ranked top 5 overall, with
top 2 per source also reported, so you can see which source is
driving demand. Cross-source scores use a log scale, but a YouTube
view and a Reddit upvote are not the same thing — compare.md says so.
Entries without a real number get engagement: null and flag
"manual/unverified". If no source yields anything, this exits
non-zero instead of inventing trends.
"""

import argparse
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    from src.config import load_config
except ImportError:  # running inside src/
    from config import load_config

USER_AGENT = "faceless-creator/1.0 (educational research tool; contact: creator)"


def _parse_date(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        # Date-only values (e.g. "2026-10-28") parse as naive; treat as UTC.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _recency_bonus(published):
    dt = _parse_date(published)
    if not dt:
        return 0, None
    days = max(0, (datetime.now(timezone.utc) - dt).days)
    return max(0, 30 - days), days


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def base_entry(source, title, topic="", channel="", url="", published="",
               engagement=None, engagement_label="", demand_signal="",
               verified=False, flag="", trending_audio="", audio_genre="",
               audio_tempo_bpm=None, audio_mood=""):
    recency, days = _recency_bonus(published)
    breakdown = {"recency": recency}
    score = float(recency)
    if isinstance(engagement, (int, float)) and engagement > 0:
        breakdown["engagement_log"] = round(math.log10(engagement + 1) * 10, 2)
        score += breakdown["engagement_log"]
    if days is not None:
        breakdown["recency_days_ago"] = days
    return {
        "source": source,
        "title": title,
        "topic": topic or title,
        "channel": channel,
        "url": url,
        "published": published,
        "engagement": engagement,
        "engagement_label": engagement_label,
        "demand_signal": demand_signal,
        "verified": verified,
        "flag": flag or ("verified" if verified else "manual/unverified"),
        "score": round(score, 2),
        "score_breakdown": breakdown,
        # Audio signal, when the source/manual input actually provides it.
        # Empty/None means "not reported by the source" — never invent a
        # trending song, genre, or tempo. See build_audio_profile().
        "trending_audio": trending_audio or "",
        "audio_genre": (audio_genre or "").lower(),
        "audio_tempo_bpm": audio_tempo_bpm,
        "audio_mood": (audio_mood or "").lower(),
    }


def _fetch_json(url, headers=None, timeout=20):
    req = Request(url, headers=headers or {"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _manual_candidates(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    return data.get("candidates", data.get("videos", []))


# ---------------------------------------------------------------- YouTube
def youtube_collector(config, manual):
    """API when YT_API_KEY is set, else manual input only."""
    api_key = os.environ.get("YT_API_KEY", "")
    if api_key:
        try:
            return _youtube_api(api_key, config.get("niche", "")), "youtube_api"
        except Exception as exc:
            print(f"WARNING: YouTube API failed ({exc}); using manual input.", file=sys.stderr)
    entries = []
    for cand in manual:
        if (cand.get("source") or "youtube") != "youtube":
            continue
        views = cand.get("views")
        entries.append(base_entry(
            "youtube", cand.get("title", ""), cand.get("topic", ""),
            cand.get("channel", ""), cand.get("url", ""), cand.get("published", ""),
            engagement=views, engagement_label="views" if views is not None else "",
            demand_signal=cand.get("demand_note") or cand.get("why_it_is_in_demand") or "",
            verified=isinstance(views, (int, float)),
            flag="" if isinstance(views, (int, float)) else "manual/unverified",
            trending_audio=cand.get("trending_audio", ""),
            audio_genre=cand.get("audio_genre", ""),
            audio_tempo_bpm=cand.get("audio_tempo_bpm"),
            audio_mood=cand.get("audio_mood", ""),
        ))
    return entries, "manual_input"


def _youtube_api(api_key, query, max_results=25):
    base = "https://www.googleapis.com/youtube/v3"
    q = urlencode({"part": "snippet", "q": query, "type": "video",
                   "order": "viewCount", "maxResults": max_results, "key": api_key})
    search = _fetch_json(f"{base}/search?{q}")
    ids = [i["id"]["videoId"] for i in search.get("items", [])]
    if not ids:
        return []
    q2 = urlencode({"part": "snippet,statistics", "id": ",".join(ids), "key": api_key})
    videos = _fetch_json(f"{base}/videos?{q2}")
    out = []
    for item in videos.get("items", []):
        stats = item.get("statistics", {})
        views = int(stats["viewCount"]) if "viewCount" in stats else None
        out.append(base_entry(
            "youtube", item["snippet"]["title"], "",
            item["snippet"].get("channelTitle", ""),
            f"https://www.youtube.com/watch?v={item['id']}",
            item["snippet"].get("publishedAt", ""), engagement=views,
            engagement_label="views", demand_signal="YouTube API search, ordered by view count",
            verified=True, flag="verified",
        ))
    return out


# ----------------------------------------------------------------- Reddit
def reddit_collector(config, manual, manual_only=False):
    """Public subreddit JSON, no key, plus manual reddit pastes.
    Returns ([entries], status). Manual entries are always included,
    so --manual-only still surfaces a pasted Reddit post."""
    entries = []
    for cand in manual:
        if (cand.get("source") or "") != "reddit":
            continue
        ups = cand.get("upvotes")
        comments = cand.get("comments") or 0
        engagement = (ups + comments) if isinstance(ups, (int, float)) else None
        entries.append(base_entry(
            "reddit", cand.get("title", ""), cand.get("topic", ""),
            cand.get("channel", ""), cand.get("url", ""), cand.get("published", ""),
            engagement=engagement, engagement_label="upvotes+comments" if engagement is not None else "",
            demand_signal=cand.get("demand_note") or "Manual paste — verify on Reddit yourself.",
            verified=isinstance(engagement, (int, float)),
            flag="" if isinstance(engagement, (int, float)) else "manual/unverified",
            trending_audio=cand.get("trending_audio", ""),
            audio_genre=cand.get("audio_genre", ""),
            audio_tempo_bpm=cand.get("audio_tempo_bpm"),
            audio_mood=cand.get("audio_mood", ""),
        ))
    if manual_only:
        return entries, "manual_input (live Reddit skipped in manual-only mode)"
    subreddits = config.get("reddit_subreddits") or []
    if not subreddits:
        # No live subreddits named: keep any manual entries, skip live.
        return entries, "manual_input (no reddit_subreddits in config.yaml)"
    keywords = config.get("niche_keywords") or [config.get("niche", "")]
    for sub in subreddits:
        for endpoint in ("hot", "top"):
            try:
                data = _fetch_json(
                    f"https://www.reddit.com/r/{sub}/{endpoint}.json?limit=20",
                    headers={"User-Agent": USER_AGENT})
            except Exception as exc:
                print(f"WARNING: Reddit r/{sub} {endpoint} failed ({exc}).", file=sys.stderr)
                continue
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                title = post.get("title", "")
                if keywords and not any(k.lower() in title.lower() for k in keywords):
                    continue
                ups = post.get("ups")
                comments = post.get("num_comments") or 0
                engagement = (ups or 0) + (comments or 0)
                entries.append(base_entry(
                    "reddit", title, "", post.get("author", ""),
                    f"https://www.reddit.com{post.get('permalink', '')}",
                    datetime.fromtimestamp(post["created_utc"], tz=timezone.utc).isoformat()
                    if post.get("created_utc") else "",
                    engagement=engagement, engagement_label="upvotes+comments",
                    demand_signal=f"r/{sub} {endpoint}: {ups} upvotes, {comments} comments",
                    verified=True, flag="verified",
                ))
    return entries, "reddit_public_json"


# ----------------------------------------------------------------- TikTok
def tiktok_collector(config, manual):
    """Research API with token, else manual paste only. Never scraped."""
    token = os.environ.get("TIKTOK_RESEARCH_TOKEN", "")
    if token:
        try:
            return _tiktok_research_api(token, config), "tiktok_research_api"
        except Exception as exc:
            print(f"WARNING: TikTok Research API failed ({exc}); using manual input.",
                  file=sys.stderr)
    entries = []
    for cand in manual:
        if (cand.get("source") or "") != "tiktok":
            continue
        entries.append(base_entry(
            "tiktok", cand.get("title", ""), cand.get("topic", ""),
            cand.get("channel", ""), cand.get("url", ""), cand.get("published", ""),
            engagement=cand.get("views"), engagement_label="views" if cand.get("views") is not None else "",
            demand_signal=cand.get("demand_note") or "Manual paste — verify on TikTok yourself.",
            verified=False, flag="manual/unverified",
            trending_audio=cand.get("trending_audio", ""),
            audio_genre=cand.get("audio_genre", ""),
            audio_tempo_bpm=cand.get("audio_tempo_bpm"),
            audio_mood=cand.get("audio_mood", ""),
        ))
    return entries, "manual_input"


def _tiktok_research_api(token, config):
    # TikTok Research API (requires approved access + token).
    # Query by niche keywords; only fields the API actually returns.
    import urllib.request
    body = json.dumps({
        "query": {"and": [{"operation": "IN", "field_name": "keyword",
                           "field_values": config.get("niche_keywords") or [config.get("niche", "")]}]},
        "max_count": 20,
    }).encode("utf-8")
    req = Request("https://open.tiktokapis.com/v2/research/video/query/",
                  data=body, method="POST",
                  headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    out = []
    for video in data.get("data", {}).get("videos", []):
        metrics = video.get("view_count") or 0
        out.append(base_entry(
            "tiktok", video.get("video_description", "")[:120], "",
            video.get("username", ""),
            f"https://www.tiktok.com/@{video.get('username', '')}/video/{video.get('id', '')}",
            "", engagement=metrics, engagement_label="views",
            demand_signal="TikTok Research API", verified=True, flag="verified",
        ))
    return out


# --------------------------------------------------------------- Facebook
def facebook_collector(config, manual):
    """Graph API with token, else manual paste only. No public scraping."""
    token = os.environ.get("FACEBOOK_GRAPH_TOKEN", "")
    if token:
        print("WARNING: Facebook Graph API video search is restricted to Pages "
              "you manage; generic public video search is not available. "
              "Falling back to manual input.", file=sys.stderr)
    entries = []
    for cand in manual:
        if (cand.get("source") or "") != "facebook":
            continue
        entries.append(base_entry(
            "facebook", cand.get("title", ""), cand.get("topic", ""),
            cand.get("channel", ""), cand.get("url", ""), cand.get("published", ""),
            engagement=cand.get("views"), engagement_label="views" if cand.get("views") is not None else "",
            demand_signal=cand.get("demand_note") or "Manual paste — verify on Facebook yourself.",
            verified=False, flag="manual/unverified",
            trending_audio=cand.get("trending_audio", ""),
            audio_genre=cand.get("audio_genre", ""),
            audio_tempo_bpm=cand.get("audio_tempo_bpm"),
            audio_mood=cand.get("audio_mood", ""),
        ))
    return entries, "manual_input"


# ------------------------------------------------------------------ Google
def google_collector(config, manual_only=False):
    """Demand/interest only — never video views. pytrends, else RSS."""
    keywords = config.get("niche_keywords") or [config.get("niche", "")]
    if manual_only:
        return [], "skipped (manual-only mode)"
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload(keywords[:5], timeframe="today 3-m")
        frame = pytrends.interest_over_time()
        entries = []
        for kw in keywords[:5]:
            if kw in frame.columns:
                series = frame[kw].dropna()
                value = int(series.iloc[-1]) if len(series) else None
                entries.append(base_entry(
                    "google", f"Search interest: {kw}", kw, "Google Trends",
                    f"https://trends.google.com/trends/explore?q={quote(kw)}", "",
                    engagement=None, engagement_label="interest (0-100)",
                    demand_signal=f"Google Trends interest over time, latest value {value} (0-100)"
                    if value is not None else "Google Trends: no data",
                    verified=True, flag="verified",
                ))
        return entries, "pytrends"
    except ImportError:
        pass
    except Exception as exc:
        print(f"WARNING: pytrends failed ({exc}); trying RSS.", file=sys.stderr)
    # Free fallback: daily trending-searches RSS (US).
    try:
        req = Request("https://trends.google.com/trends/trendingsearches/daily/rss?geo=US",
                      headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=20) as resp:
            root = ET.fromstring(resp.read())
        trending = []
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            trending.append((title, link))
        entries = []
        for kw in keywords:
            match = next(((t, l) for t, l in trending if kw.lower() in t.lower()), None)
            entries.append(base_entry(
                "google", f"Search interest: {kw}", kw, "Google Trends RSS",
                match[1] if match else f"https://trends.google.com/trends/explore?q={quote(kw)}",
                "", engagement=None, engagement_label="",
                demand_signal="In Google's daily trending searches (RSS)"
                if match else "Not in today's daily trending RSS — interest not verified",
                verified=bool(match), flag="verified" if match else "manual/unverified",
            ))
        return entries, "google_trends_rss"
    except Exception as exc:
        print(f"WARNING: Google Trends RSS failed ({exc}).", file=sys.stderr)
        return [], f"failed ({exc})"


# ------------------------------------------------------- Trending audio profile
def build_audio_profile(candidates):
    """Summarize the audio signal actually reported by the top candidates.

    Returns the most common genre, the median tempo (BPM) and the dominant
    mood, plus the named trending audios that sources/manual input reported.
    If no candidate reports any audio signal, every field is empty/None —
    the caller must not invent a profile. This profile describes STYLE
    only; music.py matches it against royalty-free tracks, never against
    the copyrighted songs themselves (see music.py).
    """
    import statistics
    from collections import Counter

    genres = [c.get("audio_genre") for c in candidates if c.get("audio_genre")]
    moods = [c.get("audio_mood") for c in candidates if c.get("audio_mood")]
    tempos = [c["audio_tempo_bpm"] for c in candidates
              if isinstance(c.get("audio_tempo_bpm"), (int, float))]
    named = []
    for cand in candidates:
        name = cand.get("trending_audio") or ""
        if name and name not in named:
            named.append(name)
    return {
        "genre": Counter(genres).most_common(1)[0][0] if genres else "",
        "tempo_bpm_median": int(statistics.median(tempos)) if tempos else None,
        "mood": Counter(moods).most_common(1)[0][0] if moods else "",
        "named_trending_audio_reported": named,
        "based_on_n_candidates": len(candidates),
        "note": ("Style profile only. Do NOT use the named trending songs "
                 "themselves — they are usually copyrighted. Match this "
                 "genre/tempo/mood with a royalty-free track (see music.py)."),
    }


# ----------------------------------------------------------------- Compare
def dedupe(entries):
    seen = {}
    for entry in entries:
        key = _norm(entry["title"]) or _norm(entry["topic"])
        if key in seen:
            existing = seen[key]
            existing.setdefault("merged_sources", []).append(entry["source"])
            if entry["score"] > existing["score"]:
                existing.update({k: v for k, v in entry.items() if k != "merged_sources"})
                existing.setdefault("merged_sources", []).append(entry["source"])
        else:
            entry["merged_sources"] = [entry["source"]]
            seen[key] = entry
    return list(seen.values())


def write_compare(path, top5, top_per_source, statuses, niche, audio_profile=None):
    lines = [
        "# Trend comparison",
        "",
        f"Niche: {niche}",
        "",
        "Cross-source scores use a log scale, but a YouTube view, a Reddit "
        "upvote, and a Google interest point are NOT the same unit. Use this "
        "table to see which source is driving demand, not as a single true ranking.",
        "",
        "| Rank | Source | Title / topic | Engagement | Demand signal | Score |",
        "|---:|---|---|---|---|---:|",
    ]
    for i, cand in enumerate(top5, start=1):
        eng = cand["engagement"]
        eng = f"{eng:,} ({cand['engagement_label']})" if isinstance(eng, (int, float)) else "null (unverified)"
        lines.append(f"| {i} | {cand['source']} | {cand['title']} | {eng} | "
                     f"{cand['demand_signal']} | {cand['score']} |")
    lines.append("")
    if audio_profile:
        lines.append("## Trending audio profile (style only, not the songs themselves)")
        lines.append("")
        lines.append(f"- Genre: {audio_profile.get('genre') or 'not reported'}")
        lines.append(f"- Median tempo: {audio_profile.get('tempo_bpm_median') or 'not reported'} BPM")
        lines.append(f"- Mood: {audio_profile.get('mood') or 'not reported'}")
        named = audio_profile.get("named_trending_audio_reported") or []
        lines.append("- Named trending audio reported by sources: "
                     + (", ".join(named) if named else "none reported"))
        lines.append("- Rule: match this genre/tempo/mood with a ROYALTY-FREE "
                     "track in music_library. Never download or use the named "
                     "trending songs themselves — that draws Content ID claims.")
        lines.append("")
    for source, entries in top_per_source.items():
        lines.append(f"## Top per source: {source} (status: {statuses.get(source, '')})")
        lines.append("")
        for cand in entries:
            lines.append(f"- {cand['title']} — score {cand['score']}, flag {cand['flag']}, {cand['url']}")
        lines.append("")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def niche_list(config):
    """Effective niche list: config `niches` if present, else legacy `niche`."""
    niches = [n for n in (config.get("niches") or []) if n]
    if niches:
        return niches
    if config.get("niche"):
        return [config["niche"]]
    return []


def collect_for_niche(config, manual, niche, manual_only=False,
                      no_reddit=False, no_google=False):
    """Run every collector for ONE niche.

    Manual candidates are filtered to this niche when they carry a
    `niche` field; entries without a niche field are only used for the
    default (first) niche, so one niche's manual list never leaks into
    another niche's ranking. Live collectors query by the niche name
    (YouTube API, TikTok Research API) and by niche keywords only for
    the default niche, where config niche_keywords apply.
    Returns (top5, top_per_source, statuses, audio_profile, all_deduped).
    """
    niches = niche_list(config)
    is_default = bool(niches) and niche == niches[0]
    run_config = dict(config)
    run_config["niche"] = niche
    if not is_default:
        # Keywords for a non-default niche are just the niche name —
        # the default niche's keywords belong to that niche only.
        run_config["niche_keywords"] = [niche]
    scoped_manual = []
    for cand in manual:
        cand_niche = cand.get("niche", "")
        if cand_niche:
            if cand_niche.strip().lower() == niche.strip().lower():
                scoped_manual.append(cand)
        elif is_default:
            scoped_manual.append(cand)
    all_entries, statuses = [], {}
    yt, statuses["youtube"] = youtube_collector(run_config, scoped_manual)
    all_entries.extend(yt)
    if not no_reddit:
        rd, statuses["reddit"] = reddit_collector(run_config, scoped_manual,
                                                  manual_only=manual_only)
        all_entries.extend(rd)
    else:
        statuses["reddit"] = "skipped (--no-reddit)"
    tk, statuses["tiktok"] = tiktok_collector(run_config, scoped_manual)
    all_entries.extend(tk)
    fb, statuses["facebook"] = facebook_collector(run_config, scoped_manual)
    all_entries.extend(fb)
    if not no_google:
        gg, statuses["google"] = google_collector(run_config, manual_only=manual_only)
        all_entries.extend(gg)
    else:
        statuses["google"] = "skipped (--no-google)"
    deduped = dedupe(all_entries)
    deduped.sort(key=lambda c: c["score"], reverse=True)
    top5 = deduped[:5]
    top_per_source = {}
    for source in ("youtube", "reddit", "tiktok", "facebook", "google"):
        per = sorted([c for c in deduped if c["source"] == source],
                     key=lambda c: c["score"], reverse=True)[:2]
        if per:
            top_per_source[source] = per
    return top5, top_per_source, statuses, build_audio_profile(top5), deduped


def rank_niches(config, manual, manual_only=False, no_reddit=False, no_google=False):
    """Rank every configured niche by demand from real sources only.

    Demand score = sum of the niche's top-5 candidate scores + 10 per
    distinct source that contributed a candidate (breadth bonus). This
    is a comparison aid, not a true cross-platform unit — see compare.md
    for why YouTube views, Reddit upvotes, and Google interest are not
    interchangeable. Niches with zero candidates score 0 and are flagged
    'no data', which means 'not measured', not 'unpopular'.
    """
    ranking = []
    # Weekly-review nudge (safe bound): the winning niche from the last
    # review gets a small +20 demand bonus in the next ranking. It nudges
    # ranking, it does not delete or ban any niche.
    preferred = (config.get("review_preferred_niche") or "").strip().lower()
    for niche in niche_list(config):
        top5, top_per_source, statuses, audio_profile, _ = collect_for_niche(
            config, manual, niche, manual_only=manual_only,
            no_reddit=no_reddit, no_google=no_google)
        sources = sorted({c["source"] for c in top5})
        verified = sum(1 for c in top5 if c.get("verified"))
        demand = round(sum(c.get("score", 0) for c in top5) + 10 * len(sources), 2)
        if preferred and niche.strip().lower() == preferred:
            demand = round(demand + 20, 2)
        top_topics = [c.get("topic") or c.get("title", "") for c in top5[:2]]
        if not top5:
            why = ("No candidates from any source for this niche in this run — "
                   "add manual input for it or set a key. No data, not low demand.")
        else:
            why = (f"Top topics: {', '.join(top_topics)}. Demand reported by "
                   f"{len(sources)} source(s) ({', '.join(sources)}); "
                   f"{verified} of {len(top5)} top candidates verified, "
                   f"the rest manual/unverified — verify before committing.")
        ranking.append({
            "niche": niche,
            "rank": 0,  # filled after sorting
            "demand_score": demand if top5 else 0,
            "n_candidates": len(top5),
            "sources": sources,
            "verified_count": verified,
            "top_topics": top_topics,
            "top_per_source": top_per_source,
            "sources_status": statuses,
            "trending_audio_profile": audio_profile,
            "why": why,
        })
    ranking.sort(key=lambda r: r["demand_score"], reverse=True)
    for i, entry in enumerate(ranking, start=1):
        entry["rank"] = i
    return ranking


def write_niche_ranking(path_md, ranking):
    lines = ["# Niche ranking (by demand in this run)", "",
             "Demand score = sum of the niche's top-5 scores + 10 per distinct "
             "source reporting demand. Scores mix units across sources, so "
             "this ranks niches for YOU to choose between — it is not a "
             "prediction of views. A niche with no candidates is 'no data', "
             "not 'unpopular'.", "",
             "| Rank | Niche | Demand score | Sources | Top topics |",
             "|---:|---|---:|---|---|"]
    for entry in ranking:
        topics = "; ".join(entry["top_topics"]) if entry["top_topics"] else "— (no data)"
        sources = ", ".join(entry["sources"]) if entry["sources"] else "none"
        lines.append(f"| {entry['rank']} | {entry['niche']} | {entry['demand_score']} | "
                     f"{sources} | {topics} |")
    lines.append("")
    for entry in ranking:
        lines.append(f"## {entry['rank']}. {entry['niche']} — why it's ranked here")
        lines.append("")
        lines.append(entry["why"])
        lines.append("")
    os.makedirs(os.path.dirname(path_md) or ".", exist_ok=True)
    with open(path_md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path_md


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/trends_input.json")
    parser.add_argument("--output", default="data/top5.json")
    parser.add_argument("--compare", default="data/compare.md")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--niche", default="",
                        help="Run for one niche only (overrides config).")
    parser.add_argument("--rank-niches", action="store_true",
                        help="Rank every niche in config niches and write data/niche_ranking.*")
    parser.add_argument("--ranking-output", default="data/niche_ranking.json")
    parser.add_argument("--ranking-compare", default="data/niche_ranking.md")
    parser.add_argument("--manual-only", action="store_true",
                        help="Only manual input; skip live Reddit/Google collectors (for offline demo/test).")
    parser.add_argument("--no-reddit", action="store_true")
    parser.add_argument("--no-google", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    manual = _manual_candidates(args.input)

    if args.rank_niches:
        ranking = rank_niches(config, manual, manual_only=args.manual_only,
                              no_reddit=args.no_reddit, no_google=args.no_google)
        os.makedirs(os.path.dirname(args.ranking_output) or ".", exist_ok=True)
        with open(args.ranking_output, "w", encoding="utf-8") as fh:
            json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                       "niches": ranking}, fh, indent=2)
        write_niche_ranking(args.ranking_compare, ranking)
        print(f"Wrote niche ranking to {args.ranking_output} and {args.ranking_compare}")
        for entry in ranking:
            print(f"  {entry['rank']}. {entry['niche']} — demand {entry['demand_score']} "
                  f"({entry['n_candidates']} candidates, sources: {', '.join(entry['sources']) or 'none'})")
        return 0

    niches = niche_list(config)
    niche = args.niche or (niches[0] if niches else config.get("niche", ""))
    top5, top_per_source, statuses, audio_profile, _ = collect_for_niche(
        config, manual, niche, manual_only=args.manual_only,
        no_reddit=args.no_reddit, no_google=args.no_google)

    if not top5:
        print(
            f"ERROR: No trending candidates for niche '{niche}' from any source. "
            f"Add entries to {args.input}, set YT_API_KEY, or name "
            "reddit_subreddits in config.yaml. Refusing to invent trending videos.",
            file=sys.stderr,
        )
        return 2

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump({
            "mode": "multi_source_compare",
            "niche": niche,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": statuses,
            "candidates": top5,
            "top_per_source": top_per_source,
            "trending_audio_profile": audio_profile,
        }, fh, indent=2)
    write_compare(args.compare, top5, top_per_source, statuses,
                  niche, audio_profile=audio_profile)
    print(f"Wrote {len(top5)} candidates for niche '{niche}' to {args.output} and comparison to {args.compare}")
    for source, status in statuses.items():
        print(f"  {source}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
