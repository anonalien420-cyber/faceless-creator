"""Build a high-quality vertical video with ffmpeg (no moviepy needed).

Visual quality rules (config: visual_quality="hd", min_resolution=1080,
video_bitrate="10M"):
- Prefer HD stock VIDEO clips (Pexels/Pixabay video API when a key is
  set, 1080p minimum) over still images — motion looks better than a
  slideshow, and a moving clip holds attention on Shorts.
- Fall back to HD still images (1920px+ wide) with Ken Burns motion
  only when no video clips are available.
- No black bars, no stretched assets: every visual is scaled to FILL
  1080x1920 and cropped (aspect preserved), never squashed.
- No low-res assets: any asset whose largest side is below
  min_resolution is REJECTED with a log line and the next best asset
  is used instead. Upscaling a 480p clip and calling it HD is not HD.
- Colour grade: a subtle contrast/saturation lift (ffmpeg eq) so
  footage looks finished, not flat — not a heavy filter.
- Captions: large, high-contrast white text with a thick black outline,
  plus a clean title card (first 3 seconds) and a progress bar.

Output: 1080x1920, 30fps, H.264 + AAC, high bitrate (default 10 Mbps,
within the 8-12 Mbps Shorts range in config). Requires ffmpeg + ffprobe.
Fails loudly if either is missing.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

try:
    from src.config import load_config
except ImportError:
    from config import load_config

WIDTH, HEIGHT, FPS = 1080, 1920, 30
FADE = 0.5  # seconds of crossfade between visual segments


def _require(tool):
    if not shutil.which(tool):
        print(f"ERROR: {tool} is required but not found on PATH.", file=sys.stderr)
        raise SystemExit(1)


def audio_duration(path):
    _require("ffprobe")
    try:
        from src.cache import ffprobe_duration
    except ImportError:
        from cache import ffprobe_duration
    value = ffprobe_duration(path)
    if value is None:
        raise RuntimeError(f"could not probe duration of {path}")
    return value


_PROBE_MEMO = {}


def probe_asset(path):
    """Return (width, height, duration_seconds, codec_type) or None.

    Memoized by path + mtime so repeated probes of the same asset (the
    render cycles a small visual pool across many chunks) are free."""
    _require("ffprobe")
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        stamp = None
    memo_key = (path, stamp)
    if memo_key in _PROBE_MEMO:
        return _PROBE_MEMO[memo_key]
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,codec_type,duration:format=duration",
         "-of", "json", path],
        capture_output=True, text=True)
    result = None
    try:
        data = json.loads(out.stdout)
        streams = data.get("streams", [])
        if streams:
            stream = streams[0]
            duration = stream.get("duration")
            if duration is None:
                # Some containers (e.g. webm) omit per-stream duration; fall
                # back to the container duration so clips are not misread as
                # still images (which would route them through zoompan).
                duration = data.get("format", {}).get("duration")
            result = (int(stream.get("width", 0)), int(stream.get("height", 0)),
                      float(duration or 0), stream.get("codec_type", "video"))
    except Exception:
        result = None
    _PROBE_MEMO[memo_key] = result
    return result


def download_file(url, dest_dir="data/stock"):
    os.makedirs(dest_dir, exist_ok=True)
    import hashlib
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("/")[-1].split("?")[0]) or "asset"
    # Prefix a short URL hash so two different URLs that share a basename
    # (e.g. both end in video.mp4) never collide in the cache.
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    dest = os.path.join(dest_dir, f"{digest}-{base}")
    if not os.path.exists(dest):
        req = urllib.request.Request(url, headers={"User-Agent": "faceless-creator/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
            shutil.copyfileobj(resp, fh)
    return dest


def fetch_stock_videos(config, keywords, per_keyword=2):
    """HD stock video clips via Pexels, then Pixabay — keys required.

    Returns a list of downloaded clip paths (1080p+ preferred). With no
    key set, returns [] and the caller falls back to stock images /
    gradient — it never invents a clip or scrapes a stock site.
    Env vars (never in config.yaml): PEXELS_API_KEY, PIXABAY_API_KEY.
    """
    links = []
    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
    queries = keywords or [config.get("niche", "")]
    try:
        try:
            from src.ops import quota_status, track_api_call
        except ImportError:
            from ops import quota_status, track_api_call
    except Exception:
        quota_status = track_api_call = None
    if pexels_key:
        for query in queries[:3]:
            if track_api_call is not None:
                try:
                    if quota_status("pexels")["warn"]:
                        print("WARNING: Pexels daily call budget nearly used; "
                              "skipping further searches (fallback visuals apply).",
                              file=sys.stderr)
                        break
                    track_api_call("pexels", 1)
                except Exception:
                    pass
            try:
                req = urllib.request.Request(
                    f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&per_page={per_keyword}&size=large",
                    headers={"Authorization": pexels_key})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.load(resp)
                for video in data.get("videos", []):
                    files = sorted(video.get("video_files", []),
                                   key=lambda f: f.get("width", 0), reverse=True)
                    hd = next((f for f in files if f.get("width", 0) >= 1080), None)
                    if hd and hd.get("link"):
                        links.append(hd["link"])
            except Exception as exc:
                print(f"WARNING: Pexels video search failed ({exc}).", file=sys.stderr)
    if not links and pixabay_key:
        for query in queries[:3]:
            if track_api_call is not None:
                try:
                    if quota_status("pixabay")["warn"]:
                        print("WARNING: Pixabay daily call budget nearly used; "
                              "skipping further searches (fallback visuals apply).",
                              file=sys.stderr)
                        break
                    track_api_call("pixabay", 1)
                except Exception:
                    pass
            try:
                url = ("https://pixabay.com/api/videos/?key=" + pixabay_key +
                       f"&q={urllib.parse.quote(query)}&per_page={max(3, per_keyword)}")
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = json.load(resp)
                for hit in data.get("hits", []):
                    videos = hit.get("videos", {})
                    large = videos.get("large") or videos.get("medium") or {}
                    if large.get("url"):
                        links.append(large["url"])
            except Exception as exc:
                print(f"WARNING: Pixabay video search failed ({exc}).", file=sys.stderr)
    return download_many(links)


def download_many(urls, max_workers=4):
    """Download stock assets concurrently (I/O bound). Preserves order,
    skips failures with a warning, and de-duplicates repeated URLs."""
    urls = list(dict.fromkeys(u for u in urls if u))
    if not urls:
        return []
    from concurrent.futures import ThreadPoolExecutor
    results = {}
    workers = max(1, min(max_workers, len(urls)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_file, u): u for u in urls}
        for fut in futures:
            url = futures[fut]
            try:
                results[url] = fut.result()
            except Exception as exc:
                print(f"WARNING: stock download failed ({url}): {exc}", file=sys.stderr)
    return [results[u] for u in urls if u in results]


# Words that carry no visual meaning for a stock search.
_SCENE_STOP = {
    "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "how", "why",
    "what", "this", "that", "is", "it", "its", "with", "your", "you", "we",
    "our", "are", "was", "were", "be", "been", "as", "at", "by", "from", "so",
    "theory", "evidence", "researchers", "actually", "still", "about", "into",
}


def section_keywords(script, max_words=3):
    """Derive a short stock-search query per script section from its title
    + salient words. Used for scene-matched B-roll. Pure function."""
    out = []
    topic = script.get("topic", "")
    for section in script.get("sections", []) or []:
        title = section.get("title", "")
        words = [w for w in re.findall(r"[A-Za-z]+", (title + " " + topic).lower())
                 if w not in _SCENE_STOP and len(w) > 3]
        seen, picked = set(), []
        for w in words:
            if w not in seen:
                seen.add(w)
                picked.append(w)
            if len(picked) >= max_words:
                break
        out.append(" ".join(picked) or topic or script.get("topic", ""))
    return out


def fetch_scene_stock(config, script, per_scene=1):
    """Scene-matched B-roll: fetch stock per section keyword set, in section
    order, so the render's visual pool follows the script's scenes. With no
    stock API key this returns [] and the caller falls back to the shared
    visual pool / gradient (current behaviour). Never invents a clip."""
    if not (os.environ.get("PEXELS_API_KEY") or os.environ.get("PIXABAY_API_KEY")):
        return []
    keywords = section_keywords(script)
    if not keywords:
        return []
    return fetch_stock_videos(config, keywords, per_keyword=per_scene)


def resolve_visuals(raw_entries, min_resolution):
    """Download (if URL), probe, and filter visuals.

    Accepts plain paths/URLs or dicts {file|url|path, type}. Returns
    (accepted, rejected) where accepted entries are dicts with
    path/type/width/height. Rejected assets are logged, never upscaled
    into the video as if they were HD.
    """
    import urllib.parse  # noqa: F401 (kept for fetch_stock_videos parity)
    accepted, rejected = [], []
    for entry in raw_entries or []:
        if isinstance(entry, dict):
            path = entry.get("file") or entry.get("url") or entry.get("path") or ""
            kind = entry.get("type", "")
        else:
            path, kind = str(entry), ""
        if not path:
            continue
        try:
            local = download_file(path) if path.startswith("http") else path
        except Exception as exc:
            rejected.append((path, f"download failed: {exc}"))
            continue
        if not os.path.exists(local):
            rejected.append((path, "file not found"))
            continue
        probed = probe_asset(local)
        if probed is None:
            rejected.append((path, "could not probe (not a readable image/video)"))
            continue
        width, height, duration, _ = probed
        if max(width, height) < int(min_resolution):
            rejected.append((path, f"below min_resolution {min_resolution}: {width}x{height}"))
            continue
        if not kind:
            kind = "video" if duration and duration > 0 and local.lower().endswith(
                (".mp4", ".mov", ".webm", ".mkv")) else "image"
        accepted.append({"path": local, "type": kind,
                         "width": width, "height": height, "duration": duration})
    for path, reason in rejected:
        print(f"REJECTED visual (using next best asset instead): {path} — {reason}")
    return accepted, rejected


def _ass_time(t):
    t = max(0.0, float(t))
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}.{int(round((t % 1) * 100)):02d}"


def _ass_safe(text):
    return str(text).replace("{", "(").replace("}", ")").replace("\n", " ")


def _caption_chunks(words, size=6):
    """Group timed words into short caption phrases (<= size words),
    breaking on sentence-ending punctuation so a phrase reads naturally."""
    chunks, current = [], []
    for w in words:
        current.append(w)
        ends_sentence = bool(re.search(r"[.!?]$", w.get("text", "")))
        if len(current) >= size or ends_sentence:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def load_timings(audio_path):
    """Load the narration word/sentence timings sidecar, if present.

    narrate.py writes <audio>.timings.json (word timings from edge-tts
    WordBoundary, or sentence cues from the CLI SRT fallback); music.py
    carries it alongside the mixed track. Returns the dict or None.
    """
    path = audio_path + ".timings.json"
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("words") or data.get("sentences"):
            return data
    except (OSError, ValueError):
        pass
    return None


def make_ass(script_text, duration, path, width=1080, height=1920, fontsize=72,
             timings=None, brand=None, safe_zone=0.25, karaoke=True):
    """Write the caption .ass file.

    With word timings (timings["words"]) and karaoke=True, captions are
    synced to the narration and the ACTIVE word is highlighted in the
    brand accent colour (one event per word, whole phrase on screen).
    With sentence timings, each cue shows for its real span. With no
    timings, falls back to evenly-timed 7-word chunks (the old behaviour).

    Captions are kept out of the bottom `safe_zone` fraction of a vertical
    Short (the Shorts UI covers roughly the bottom 25%), so they are never
    hidden behind the like/comment/share buttons.
    """
    try:
        from src.brand import ass_color
        from src.models import Brand
    except ImportError:
        from brand import ass_color
        from models import Brand
    brand = brand or Brand()
    primary = ass_color(brand.text_color)
    outline = ass_color(brand.outline_color)
    accent = ass_color(brand.accent)
    font = brand.font or "DejaVu Sans"
    vertical = height > width
    # MarginV is the distance from the bottom edge for bottom-aligned (2)
    # text. Push captions above the Shorts UI safe zone on vertical video.
    margin_v = int(height * safe_zone) + 30 if vertical else 60
    header = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}",
              f"PlayResY: {height}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
              "[V4+ Styles]",
              "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
              "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
              "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
              "Alignment, MarginL, MarginR, MarginV, Encoding",
              f"Style: Default,{font},{fontsize},{primary},{accent},{outline},"
              f"&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,{margin_v},1",
              "", "[Events]",
              "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    events = []

    words = (timings or {}).get("words") if timings else None
    sentences = (timings or {}).get("sentences") if timings else None
    if words and karaoke:
        for chunk in _caption_chunks(words):
            texts = [_ass_safe(w["text"]) for w in chunk]
            for i, w in enumerate(chunk):
                start = float(w["start"])
                end = float(chunk[i + 1]["start"]) if i + 1 < len(chunk) else float(w["end"])
                end = max(end, start + 0.05)
                rendered = " ".join(
                    ("{\\c" + accent + "}" + t + "{\\c" + primary + "}") if j == i else t
                    for j, t in enumerate(texts))
                events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{rendered}")
    elif words or sentences:
        cues = words or sentences
        # Sentence cues (or word timings with karaoke off): one event per
        # cue/phrase spanning its real time, no per-word highlight.
        groups = _caption_chunks(cues) if words else [[c] for c in cues]
        for group in groups:
            start = float(group[0]["start"])
            end = float(group[-1]["end"])
            text = _ass_safe(" ".join(g["text"] for g in group))
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}")
    else:
        # No timings: evenly-timed 7-word chunks (legacy fallback).
        chunks, chunk = [], []
        for word in script_text.split():
            chunk.append(word)
            if len(chunk) >= 7:
                chunks.append(" ".join(chunk))
                chunk = []
        if chunk:
            chunks.append(" ".join(chunk))
        per = duration / max(len(chunks), 1)
        for i, text in enumerate(chunks):
            events.append(f"Dialogue: 0,{_ass_time(i * per)},{_ass_time((i + 1) * per)},"
                          f"Default,,0,0,0,,{_ass_safe(text)}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(header + events))
    return path


def _write_drawtext_file(directory, name, text):
    """Write dynamic drawtext text to a file (no filtergraph quoting).

    An inline drawtext=text='...' value cannot carry an apostrophe:
    the escaping that ffmpeg's filtergraph parser accepts is stripped
    again by drawtext's own option parser, which then sees a bare
    quote, so any prompt like "Here's why it works:" aborted the
    render with rc=234. Reading the text from a file sidesteps both
    parsers entirely (drawtext=textfile=...:expansion=none).
    """
    path = os.path.join(directory, f"{name}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(text))
    return path


def _drawtext_path(path):
    """Escape a generated textfile path for the filtergraph parser.

    Only backslash and colon are escaped; these are mkdtemp paths
    (alphanumeric + underscore), so this never mangles real input.
    """
    return path.replace("\\", "\\\\").replace(":", "\\:")


def _fit_hook_text(text, width, fontsize):
    """Wrap a hook into lines that fit the video frame.

    drawtext does not wrap text automatically. Keep a five-percent side
    margin and conservatively budget one em per character (plus the
    outline) so even wide glyphs do not clip. Scale the requested font
    size for small render dimensions; full-size 1080p/1920p output keeps
    its existing hook size.
    """
    normalized = " ".join(str(text).split())
    fontsize = max(1, int(fontsize))
    if not normalized:
        return "", fontsize

    scale = min(1.0, max(0.0, width) / 1080.0)
    fitted_fontsize = max(12, int(fontsize * scale))
    side_margin = int(width * 0.05)
    available_width = max(1, width - 2 * side_margin - 4)  # 2px outline each side
    max_chars = max(1, available_width // fitted_fontsize)

    lines, current = [], ""
    for word in normalized.split():
        # Keep unusually long, unbroken words inside the same width limit.
        while len(word) > max_chars:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        if not word:
            continue
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)

    return "\n".join(lines), fitted_fontsize


def _fill_filter(width, height):
    """Scale to fill WxH and crop, preserving aspect (no stretch, no bars)."""
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps=30,format=yuv420p")


def _chapter_lower_thirds(script, duration, drawtext_dir, width, height,
                          bfont, btext, boutline, baccent, fontsize):
    """Branded lower-third title cards for each long-form section, timed
    by the section's word-count share of the runtime (same model as the
    YouTube chapters in run.py). Each shows for ~4s at its boundary."""
    sections = script.get("sections") or []
    total_words = max(1, len(script.get("text", "").split()))
    intro_words = max(1, total_words - sum(len(s.get("text", "").split()) for s in sections)
                      - len(script.get("cta", "").split()))
    segments = [("Intro", intro_words)] + [
        (s.get("title", ""), len(s.get("text", "").split())) for s in sections]
    filters = []
    elapsed = 0.0
    lt_font = max(28, fontsize - 12)
    for idx, (title_text, words) in enumerate(segments):
        start = elapsed
        elapsed += duration * words / total_words
        if not title_text or idx == 0:
            continue  # the opening title card already covers the intro
        bar_y = height - 150
        label = _drawtext_path(_write_drawtext_file(
            drawtext_dir, f"chapter_{idx}", title_text[:60]))
        enable = f"between(t,{start:.2f},{start + 4:.2f})"
        filters.append(
            f"drawbox=x=0:y={bar_y}:w={width}:h=80:color={boutline}@0.55:t=fill:enable='{enable}'")
        filters.append(
            f"drawbox=x=0:y={bar_y}:w=10:h=80:color={baccent}@0.95:t=fill:enable='{enable}'")
        filters.append(
            f"drawtext=textfile={label}:expansion=none:font={bfont}:fontsize={lt_font}:"
            f"fontcolor={btext}:borderw=2:bordercolor={boutline}:x=40:y={bar_y + 22}:enable='{enable}'")
    return filters


def _real_source_title(source):
    """A real, non-placeholder source title, or '' (never invent one)."""
    if isinstance(source, dict):
        title = source.get("title", "") or source.get("url", "")
    else:
        title = str(source or "")
    title = title.strip()
    if not title or any(m in title.lower() for m in ("placeholder", "do not publish")):
        return ""
    return title


def _citation_lower_thirds(script, duration, drawtext_dir, width, height,
                           bfont, btext, boutline, baccent, fontsize):
    """On-screen source citations for history-mystery videos — a trust
    signal that visibly separates accurate content from misinformation.

    Shows the shock hook's source at the opening, and the primary verified
    source at each KNOWN section (timed by word-count share of runtime).
    Only real, non-placeholder source titles are shown; nothing invented.
    Returns [] for non-history scripts or when no real source exists.
    """
    if script.get("style") != "history_mystery":
        return []
    primary = ""
    for source in script.get("sources") or []:
        primary = _real_source_title(source)
        if primary:
            break
    shock_src = _real_source_title((script.get("shock_hook") or {}).get("source") or {})
    if not primary and not shock_src:
        return []
    filters = []
    cite_font = max(18, fontsize - 28)
    vertical = height > width
    # Top badge on Shorts (above the caption safe zone); lower-third on long.
    y = 110 if vertical else height - 90
    counter = [0]

    def badge(label, start, end):
        text = "Source: " + label[:50]
        path = _drawtext_path(_write_drawtext_file(
            drawtext_dir, f"cite_{counter[0]}", text))
        counter[0] += 1
        enable = f"between(t,{start:.2f},{end:.2f})"
        filters.append(
            f"drawbox=x=30:y={y - 6}:w=8:h={cite_font + 12}:color={baccent}@0.95:t=fill:enable='{enable}'")
        filters.append(
            f"drawtext=textfile={path}:expansion=none:font={bfont}:fontsize={cite_font}:"
            f"fontcolor={btext}:borderw=2:bordercolor={boutline}:x=48:y={y}:enable='{enable}'")

    if shock_src:
        badge(shock_src, 0.5, 5.0)
    sections = script.get("sections") or []
    total_words = max(1, len(script.get("text", "").split()))
    intro_words = max(1, total_words - sum(len(s.get("text", "").split()) for s in sections)
                      - len(script.get("cta", "").split()))
    elapsed = duration * intro_words / total_words
    for section in sections:
        words = len(section.get("text", "").split())
        start = elapsed
        elapsed += duration * words / total_words
        if section.get("tier") == "KNOWN" and primary:
            badge(primary, start, start + 4.0)
    return filters


def _watermark_filter(brand, width, in_label, out_label):
    """Semi-transparent brand watermark overlay (own asset), top-right.

    Returns filter_complex statements that load the image via the movie
    source and overlay it on `in_label`, producing `out_label`. Returns
    [] when no watermark is configured or the file is missing. The path
    is escaped for the filtergraph parser (backslash, colon, quote)."""
    path = getattr(brand, "watermark", "") or ""
    if not path or not os.path.exists(path):
        return []
    esc = path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return [f"movie='{esc}',format=rgba,colorchannelmixer=aa=0.5,"
            f"scale={max(60, width // 8)}:-1[wm]",
            f"{in_label}[wm]overlay=W-w-30:30{out_label}"]


def _apply_loop_ending(output, duration, width, height, bitrate="10M"):
    """Shorts auto-loop on YouTube. Fade the ACTUAL first frame back in
    over the last 0.4s so the replay reads as one intentional loop instead
    of a hard cut from end card to title card. Duration and audio are
    untouched (audio stream copied), so narration sync and the QA
    duration gate are unaffected. Shorts only; no-op on failure."""
    if height <= width or duration < 2.0:
        return False
    tmp_dir = tempfile.mkdtemp(prefix="loop_end_")
    first = os.path.join(tmp_dir, "first.png")
    tmp_out = output + ".loop.mp4"
    try:
        grab = subprocess.run(
            ["ffmpeg", "-y", "-i", output, "-frames:v", "1", first],
            capture_output=True, timeout=120)
        if grab.returncode != 0 or not os.path.exists(first):
            return False
        fade_start = max(0.0, duration - 0.4)
        graph = (f"[1:v]format=yuva420p,fade=t=in:st={fade_start:.2f}:d=0.4:alpha=1[ov];"
                 f"[0:v][ov]overlay=enable='gte(t,{fade_start:.2f})':shortest=1[v]")
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", output, "-loop", "1", "-i", first,
             "-filter_complex", graph, "-map", "[v]", "-map", "0:a",
             "-t", f"{duration:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-b:v", bitrate, "-c:a", "copy", tmp_out],
            capture_output=True, timeout=600)
        if result.returncode != 0 or not os.path.exists(tmp_out) or os.path.getsize(tmp_out) == 0:
            return False
        os.replace(tmp_out, output)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _finish_render(output, duration, width, height, loop_ending, cover_frame,
                   bitrate="10M"):
    """Post-render polish, best-effort: a failed loop/cover step never
    fails the render itself (the video is already valid)."""
    if loop_ending and _apply_loop_ending(output, duration, width, height, bitrate):
        print("Loop ending: first frame fades back in over the last 0.4s (Shorts replay).")
    if cover_frame:
        cover = _extract_cover_frame(output)
        if cover:
            print(f"Cover frame -> {cover}")


def _extract_cover_frame(output, at=0.5):
    """Write <video>.cover.jpg — a clean early frame (title + hook on
    screen) for the Shorts shelf / custom-thumbnail use. Best-effort."""
    cover = os.path.splitext(output)[0] + ".cover.jpg"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(at), "-i", output,
             "-frames:v", "1", "-q:v", "2", cover],
            capture_output=True, timeout=120)
        if result.returncode == 0 and os.path.exists(cover) and os.path.getsize(cover) > 0:
            return cover
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def build_video(script, audio_path, output, visuals=None, duration=None,
                bitrate="10M", min_resolution=1080, width=1080, height=1920,
                end_card_text="Subscribe for the next one", brand=None,
                transitions="varied", safe_zone=0.25, karaoke=True,
                show_citations=True, loop_ending=False, cover_frame=False):
    """Render one video. Shorts default 1080x1920; long-form 1920x1080.

    `script` is a dict with text/topic/hook (see script.py). Captions are
    written to output + ".ass" (QA also checks that path).

    Retention pacing (see README "Retention editing"):
    - First 3 seconds: title card + hook line on screen immediately,
      no dead air — the payoff starts at t=0, not after an intro.
    - Pattern interrupts: the visual re-cuts at least every 25s in
      longs and every 10s in Shorts (visual switch, alternating
      zoom-in / zoom-punch, plus a short on-screen prompt at each
      boundary), so the video never sits on one static Ken Burns shot.
    - No long silent gaps: cuts are driven by narration length, and
      the QA gate (silencedetect) rejects silent stretches over 2s.
    - End: a clear end card in the last 3 seconds (next-video/series
      CTA — callers pass a funnel end card for Shorts).
    """
    _require("ffmpeg")
    try:
        from src.brand import drawtext_color
        from src.models import Brand
    except ImportError:
        from brand import drawtext_color
        from models import Brand
    brand = brand or Brand()
    bfont = brand.font or "DejaVu Sans"
    btext = drawtext_color(brand.text_color)
    boutline = drawtext_color(brand.outline_color)
    baccent = drawtext_color(brand.accent)
    duration = duration or audio_duration(audio_path)
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    ass_path = output + ".ass"
    fontsize = 72 if height > width else 54
    # Caption font scales with frame width so small renders (QA rebuilds,
    # tests) never overflow horizontally; full 1080p/1920p keeps 72/54.
    caption_fontsize = max(14, int(fontsize * min(1.0, width / 1080.0)))
    timings = load_timings(audio_path)
    make_ass(script["text"], duration, ass_path, width=width, height=height,
             fontsize=caption_fontsize, timings=timings, brand=brand,
             safe_zone=safe_zone, karaoke=karaoke)
    title = script["topic"].title()[:60]
    hook_line = (script.get("hook", "") or "").split(". ")[0][:80]
    hook_fontsize = max(28, fontsize - 18)
    # Dynamic overlay text is read from files, never embedded in the
    # filtergraph (apostrophes in prompts broke the render, rc=234).
    drawtext_dir = tempfile.mkdtemp(prefix="deep_scan_drawtext_")
    title = _drawtext_path(_write_drawtext_file(drawtext_dir, "title", title))
    if hook_line:
        hook_text, hook_fontsize = _fit_hook_text(
            hook_line, width, hook_fontsize)
        hook_line = _drawtext_path(
            _write_drawtext_file(drawtext_dir, "hook", hook_text))
    accepted, _rejected = resolve_visuals(visuals or [], min_resolution)
    # Pattern-interrupt interval: 25s longs, 10s Shorts.
    interrupt = 25.0 if width > height else 10.0
    import math as _math
    chunk_count = max(1, _math.ceil(duration / interrupt))
    chunk = duration / chunk_count
    # Caption/title/progress filters, applied after the visual chain.
    # Brand accent drives the progress bar + title underline so every
    # video reads as one channel.
    overlay = [
        f"drawbox=x=0:y={height - 50}:w='{width}*t/{duration:.2f}':h=12:color={baccent}@0.9:t=fill",
        f"drawbox=x=(w-{min(width - 120, 720)})/2:y={200 + fontsize + 8}:"
        f"w={min(width - 120, 720)}:h=6:color={baccent}@0.95:t=fill:enable='lt(t,3)'",
        f"drawtext=textfile={title}:expansion=none:font={bfont}:fontsize={fontsize}:fontcolor={btext}:"
        f"borderw=3:bordercolor={boutline}:x=(w-text_w)/2:y=200:enable='lt(t,3)'",
        f"ass={ass_path}",
    ]
    if hook_line:
        overlay.append(
            f"drawtext=textfile={hook_line}:expansion=none:font={bfont}:fontsize={hook_fontsize}:"
            f"fontcolor={btext}:borderw=2:bordercolor={boutline}:x=(w-text_w)/2:"
            f"y={200 + fontsize + 20}:enable='lt(t,5)'")
    prompts = ["The key part:", "Here's why it works:", "Don't miss this:", "Quick check:"]
    for k in range(1, chunk_count):
        t = k * chunk
        prompt = _drawtext_path(_write_drawtext_file(
            drawtext_dir, f"prompt_{k}", prompts[(k - 1) % len(prompts)]))
        overlay.append(
            f"drawtext=textfile={prompt}:expansion=none:font={bfont}:fontsize={max(32, fontsize - 14)}:"
            f"fontcolor={baccent}:borderw=3:bordercolor={boutline}:x=(w-text_w)/2:"
            f"y={height // 3}:enable='between(t,{t:.2f},{t + 2:.2f})'")
    # Long-form chapter lower-thirds: each section title appears as a
    # branded bar at its approximate start (word-count share of runtime).
    if width > height and script.get("sections"):
        overlay.extend(_chapter_lower_thirds(
            script, duration, drawtext_dir, width, height, bfont, btext,
            boutline, baccent, fontsize))
    # On-screen source citations (history-mystery trust signal): show the
    # verified source when a KNOWN fact / the shock hook is on screen.
    if show_citations:
        overlay.extend(_citation_lower_thirds(
            script, duration, drawtext_dir, width, height, bfont, btext,
            boutline, baccent, fontsize))
    end_card = _drawtext_path(
        _write_drawtext_file(drawtext_dir, "end_card", end_card_text))
    overlay.append(
        f"drawtext=textfile={end_card}:expansion=none:font={bfont}:"
        f"fontsize={fontsize}:fontcolor={btext}:borderw=3:bordercolor={boutline}:"
        f"x=(w-text_w)/2:y={height - 220}:enable='gt(t,{duration - 3:.2f})'")
    # Optional brand watermark (own asset), top-right, semi-transparent.
    wm = _watermark_filter(brand, width, "[vpre]", "[vout]")
    if not accepted:
        # Animated gradient fallback (no asset to grade).
        grad = (f"gradients=s={width}x{height}:c0=0x0f172a:c1=0x1e3a8a:"
                f"x0=0:y0=0:x1={width}:y1={height}:duration={duration}")
        if wm:
            graph = [f"[0:v]{','.join(overlay)}[vpre]"] + wm
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", grad,
                   "-i", audio_path, "-filter_complex", ";".join(graph),
                   "-map", "[vout]", "-map", "1:a",
                   "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   "-b:v", bitrate, "-maxrate", "12M", "-bufsize", "20M",
                   "-c:a", "aac", "-shortest", output]
        else:
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", grad,
                   "-i", audio_path, "-vf", ",".join(overlay),
                   "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   "-b:v", bitrate, "-maxrate", "12M", "-bufsize", "20M",
                   "-c:a", "aac", "-shortest", output]
        try:
            subprocess.run(cmd, check=True)
        finally:
            shutil.rmtree(drawtext_dir, ignore_errors=True)
        _finish_render(output, duration, width, height, loop_ending, cover_frame)
        print(f"Video -> {output} ({duration:.1f}s, {width}x{height}, gradient fallback)")
        return output

    # Build one filtered stream per pattern-interrupt chunk, then
    # crossfade them. Visuals cycle so a short list still re-cuts at
    # every interrupt; zoom alternates in/out as a zoom punch.
    n = chunk_count
    seg = chunk
    # Each xfade overlaps FADE seconds, so a chain of n segments of length
    # `seg` would end (n-1)*FADE seconds EARLY and -shortest would chop the
    # narration's ending. Give every segment FADE seconds of extra tail and
    # place transition i at offset i*seg - FADE: the chain then totals
    # exactly n*seg == duration, so audio and video stay in sync.
    seg_len = seg + FADE if n > 1 else duration
    inputs = []
    filters = []
    # One ffmpeg input per chunk (same file may be listed several times).
    for i in range(n):
        vis = accepted[i % len(accepted)]
        if vis["type"] == "image":
            inputs += ["-loop", "1", "-i", vis["path"]]
            zoom = ("min(zoom+0.0008,1.3)" if i % 2 == 0
                    else "max(1.25-0.0008*on,1.0)")
            # Scale to FILL the 2x frame and crop (aspect preserved, no
            # stretch), then Ken Burns zoom anchored on the centre — not
            # the top-left corner — and force square pixels so the output
            # displays at the intended aspect.
            filters.append(
                f"[{i}:v]scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
                f"crop={width * 2}:{height * 2},"
                f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={int(seg_len * FPS)}:s={width}x{height}:fps={FPS},"
                f"setsar=1,format=yuv420p[v{i}]")
        else:
            # Loop short clips so a segment always has enough frames even
            # when the source clip is shorter than the interrupt interval.
            inputs += ["-stream_loop", "-1", "-i", vis["path"]]
            clip_dur = vis.get("duration") or 0
            start = 0.0
            if clip_dur and clip_dur > seg_len:
                start = min(i * 2.0, clip_dur - seg_len)
            filters.append(
                f"[{i}:v]trim={start:.2f}:{start + seg_len:.2f},setpts=PTS-STARTPTS,"
                f"{_fill_filter(width, height)},setsar=1[v{i}]")
    audio_idx = n
    inputs += ["-i", audio_path]
    if n == 1:
        filters.append("[v0]copy[vx]")
    else:
        # xfade chain: transition i starts at i*seg - FADE so the final
        # stream length is exactly n*seg (see seg_len note above).
        current = "[v0]"
        # Varied transitions: rotate a small set so the video does not sit
        # on one crossfade. "zoomin" gives a zoom-punch on emphasis cuts;
        # the rest are clean dissolves/wipes. transitions="fade" keeps the
        # classic all-crossfade look.
        varied = ["fade", "dissolve", "smoothleft", "zoomin", "circleopen"]
        for i in range(1, n):
            offset = i * seg - FADE
            kind = varied[(i - 1) % len(varied)] if transitions == "varied" else "fade"
            filters.append(f"{current}[v{i}]xfade=transition={kind}:duration={FADE}:offset={offset:.2f}[x{i}]")
            current = f"[x{i}]"
        filters.append(f"{current}copy[vx]")
    filters.append("[vx]eq=contrast=1.05:saturation=1.10:brightness=0.02[vgrade]")
    if wm:
        filters.append(f"[vgrade]{','.join(overlay)}[vpre]")
        filters.extend(wm)
    else:
        filters.append(f"[vgrade]{','.join(overlay)}[vout]")
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", f"{audio_idx}:a",
            "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-b:v", bitrate, "-maxrate", "12M", "-bufsize", "20M",
            "-c:a", "aac", "-shortest", output])
    try:
        subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(drawtext_dir, ignore_errors=True)
    _finish_render(output, duration, width, height, loop_ending, cover_frame, bitrate)
    kinds = ",".join(v["type"] for v in accepted)
    print(f"Video -> {output} ({duration:.1f}s, {width}x{height}, "
          f"{len(accepted)} visual(s) in {n} chunk(s): {kinds}, {bitrate})")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/scripts.json")
    parser.add_argument("--audio-dir", default="data/audio_mixed")
    parser.add_argument("--outdir", default="data/videos")
    parser.add_argument("--images", nargs="*", default=[])
    parser.add_argument("--visuals", nargs="*", default=[])
    parser.add_argument("--visuals-file", default="")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--bitrate", default="")
    parser.add_argument("--format", default="short", choices=["short", "long"],
                        help="short = 1080x1920 vertical; long = 1920x1080 16:9.")
    parser.add_argument("--end-card-text", default="Subscribe for the next one",
                        help="End-card CTA shown in the last 3 seconds (Shorts funnel: 'Watch the full video today').")
    parser.add_argument("--fetch-stock", action="store_true",
                        help="Fetch HD stock video clips (needs PEXELS_API_KEY or PIXABAY_API_KEY).")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    try:
        from src.models import Brand
    except ImportError:
        from models import Brand
    brand = Brand.from_config(config)
    transitions = config.get("transitions", "varied") or "varied"
    safe_zone = float(config.get("captions_safe_zone", 0.25) or 0.25)
    karaoke = bool(config.get("captions_karaoke", True))
    show_citations = bool(config.get("show_citations", True))
    loop_ending = bool(config.get("loop_ending", True))
    cover_frame = bool(config.get("cover_frame", True))
    if args.format == "long":
        width, height = 1920, 1080
        bitrate = args.bitrate or config.get("long_video_bitrate", "12M")
    else:
        width, height = 1080, 1920
        bitrate = args.bitrate or config.get("video_bitrate", "10M")
    min_resolution = int(config.get("min_resolution", 1080) or 1080)
    with open(args.input, encoding="utf-8") as fh:
        scripts = json.load(fh)
    os.makedirs(args.outdir, exist_ok=True)
    base_visuals = list(args.visuals) + list(args.images)
    if args.visuals_file and os.path.exists(args.visuals_file):
        with open(args.visuals_file, encoding="utf-8") as fh:
            base_visuals.extend(json.load(fh))
    if args.fetch_stock:
        # Stock video first, then stock images — per visual_source order.
        stock = fetch_stock_videos(config, config.get("niche_keywords") or [])
        base_visuals = stock + base_visuals
    if not base_visuals:
        # Config order: stock video URLs first, then stock images.
        base_visuals = (list(config.get("stock_video_urls") or [])
                        + list(config.get("stock_image_urls") or []))
    try:
        from src import cache
    except ImportError:
        import cache
    cache_enabled = bool(config.get("cache_enabled", True))
    max_workers = int(config.get("max_workers", 0) or 0)

    def render_one(script):
        slug = re.sub(r"[^a-z0-9]+", "-", script["topic"].lower()).strip("-") or "script"
        audio = os.path.join(args.audio_dir, f"{script['rank']:02d}-{slug}.mp3")
        if not os.path.exists(audio):
            audio = os.path.join("data/audio", f"{script['rank']:02d}-{slug}.mp3")
        output = os.path.join(args.outdir, f"{script['rank']:02d}-{slug}.mp4")
        # Scene-matched B-roll: per-section stock (needs a key), ordered to
        # follow the script's scenes; falls back to the shared pool.
        visuals = base_visuals
        if args.fetch_stock and config.get("scene_broll", True):
            scene = fetch_scene_stock(config, script)
            if scene:
                visuals = scene + base_visuals
        # Cache: skip re-render when script + audio + visuals are unchanged.
        key = cache.make_key(script.get("text", ""), audio, tuple(visuals or []),
                             width, height, bitrate, transitions,
                             loop_ending, cover_frame)
        if cache_enabled and cache.is_cached("video", key, output):
            print(f"Video -> {output} (cached, unchanged script/audio/visuals)")
            if cover_frame and not os.path.exists(os.path.splitext(output)[0] + ".cover.jpg"):
                _extract_cover_frame(output)
            return output
        build_video(script, audio, output, visuals=visuals or None,
                    bitrate=bitrate, min_resolution=min_resolution,
                    width=width, height=height,
                    end_card_text=args.end_card_text, brand=brand,
                    transitions=transitions, safe_zone=safe_zone, karaoke=karaoke,
                    show_citations=show_citations, loop_ending=loop_ending,
                    cover_frame=cover_frame)
        if cache_enabled:
            cache.mark_cached("video", key, output)
        return output

    # Parallel renders: ffmpeg runs in subprocesses (GIL released), so a
    # thread pool gives near-linear speedup across videos. max_workers=0
    # auto-sizes to the CPU count (capped at 4 to bound memory).
    if len(scripts) > 1:
        from concurrent.futures import ThreadPoolExecutor
        workers = max_workers or min(4, (os.cpu_count() or 2))
        workers = max(1, min(workers, len(scripts)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(render_one, scripts))
    else:
        for script in scripts:
            render_one(script)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
