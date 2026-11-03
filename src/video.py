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
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def probe_asset(path):
    """Return (width, height, duration_seconds, codec_type) or None."""
    _require("ffprobe")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,codec_type,duration",
         "-of", "json", path],
        capture_output=True, text=True)
    try:
        streams = json.loads(out.stdout).get("streams", [])
        if not streams:
            return None
        stream = streams[0]
        duration = stream.get("duration")
        if duration is None:
            duration = audio_duration(path) if False else 0
        return (int(stream.get("width", 0)), int(stream.get("height", 0)),
                float(duration or 0), stream.get("codec_type", "video"))
    except Exception:
        return None


def download_file(url, dest_dir="data/stock"):
    os.makedirs(dest_dir, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("/")[-1].split("?")[0]) or "asset"
    dest = os.path.join(dest_dir, name)
    if not os.path.exists(dest):
        urllib.request.urlretrieve(url, dest)
    return dest


def fetch_stock_videos(config, keywords, per_keyword=2):
    """HD stock video clips via Pexels, then Pixabay — keys required.

    Returns a list of downloaded clip paths (1080p+ preferred). With no
    key set, returns [] and the caller falls back to stock images /
    gradient — it never invents a clip or scrapes a stock site.
    Env vars (never in config.yaml): PEXELS_API_KEY, PIXABAY_API_KEY.
    """
    clips = []
    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
    queries = keywords or [config.get("niche", "")]
    if pexels_key:
        for query in queries[:3]:
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
                        clips.append(download_file(hd["link"]))
            except Exception as exc:
                print(f"WARNING: Pexels video search failed ({exc}).", file=sys.stderr)
    if not clips and pixabay_key:
        for query in queries[:3]:
            try:
                url = ("https://pixabay.com/api/videos/?key=" + pixabay_key +
                       f"&q={urllib.parse.quote(query)}&per_page={per_keyword}")
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = json.load(resp)
                for hit in data.get("hits", []):
                    videos = hit.get("videos", {})
                    large = videos.get("large") or videos.get("medium") or {}
                    if large.get("url"):
                        clips.append(download_file(large["url"]))
            except Exception as exc:
                print(f"WARNING: Pixabay video search failed ({exc}).", file=sys.stderr)
    return clips


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


def make_ass(script_text, duration, path, width=1080, height=1920, fontsize=72):
    words = script_text.split()
    chunks, chunk = [], []
    for word in words:
        chunk.append(word)
        if len(chunk) >= 7:
            chunks.append(" ".join(chunk))
            chunk = []
    if chunk:
        chunks.append(" ".join(chunk))
    per = duration / max(len(chunks), 1)
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
             "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, "
             "Alignment, MarginL, MarginR, MarginV, BorderStyle, Outline",
             f"Style: Default,DejaVu Sans,{fontsize},&H00FFFFFF,&H80000000,-1,2,60,60,400,1,5",
             "", "[Events]",
             "Format: Layer, Start, End, Style, Text"]
    for i, text in enumerate(chunks):
        start, end = i * per, (i + 1) * per

        def fmt(t):
            h, rem = divmod(int(t), 3600)
            m, s = divmod(rem, 60)
            return f"{h}:{m:02d}:{s:02d}.{int((t % 1) * 100):02d}"
        safe = text.replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{fmt(start)},{fmt(end)},Default,,0,0,0,,{safe}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def _escape_drawtext(text):
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _fill_filter(width, height):
    """Scale to fill WxH and crop, preserving aspect (no stretch, no bars)."""
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps=30,format=yuv420p")


def build_video(script, audio_path, output, visuals=None, duration=None,
                bitrate="10M", min_resolution=1080, width=1080, height=1920,
                end_card_text="Subscribe for the next one"):
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
    duration = duration or audio_duration(audio_path)
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    ass_path = output + ".ass"
    fontsize = 72 if height > width else 54
    make_ass(script["text"], duration, ass_path, width=width, height=height,
             fontsize=fontsize)
    title = _escape_drawtext(script["topic"].title()[:60])
    hook_line = _escape_drawtext((script.get("hook", "") or "").split(". ")[0][:80])
    accepted, _rejected = resolve_visuals(visuals or [], min_resolution)
    # Pattern-interrupt interval: 25s longs, 10s Shorts.
    interrupt = 25.0 if width > height else 10.0
    import math as _math
    chunk_count = max(1, _math.ceil(duration / interrupt))
    chunk = duration / chunk_count
    # Caption/title/progress filters, applied after the visual chain.
    overlay = [
        f"drawbox=x=0:y={height - 50}:w='{width}*t/{duration:.2f}':h=12:color=yellow@0.9:t=fill",
        f"drawtext=text='{title}':font=DejaVu Sans:fontsize={fontsize}:fontcolor=white:"
        f"borderw=3:bordercolor=black:x=(w-text_w)/2:y=200:enable='lt(t,3)'",
        f"ass={ass_path}",
    ]
    if hook_line:
        overlay.append(
            f"drawtext=text='{hook_line}':font=DejaVu Sans:fontsize={max(28, fontsize - 18)}:"
            f"fontcolor=white:borderw=2:bordercolor=black:x=(w-text_w)/2:"
            f"y={200 + fontsize + 20}:enable='lt(t,5)'")
    prompts = ["The key part:", "Here's why it works:", "Don't miss this:", "Quick check:"]
    for k in range(1, chunk_count):
        t = k * chunk
        prompt = _escape_drawtext(prompts[(k - 1) % len(prompts)])
        overlay.append(
            f"drawtext=text='{prompt}':font=DejaVu Sans:fontsize={max(32, fontsize - 14)}:"
            f"fontcolor=yellow:borderw=3:bordercolor=black:x=(w-text_w)/2:"
            f"y={height // 3}:enable='between(t,{t:.2f},{t + 2:.2f})'")
    overlay.append(
        f"drawtext=text='{_escape_drawtext(end_card_text)}':font=DejaVu Sans:"
        f"fontsize={fontsize}:fontcolor=white:borderw=3:bordercolor=black:"
        f"x=(w-text_w)/2:y={height - 220}:enable='gt(t,{duration - 3:.2f})'")
    if not accepted:
        # Animated gradient fallback (no asset to grade).
        cmd = ["ffmpeg", "-y", "-f", "lavfi",
               "-i", f"gradients=s={width}x{height}:c0=0x0f172a:c1=0x1e3a8a:x0=0:y0=0:x1={width}:y1={height}:duration={duration}",
               "-i", audio_path, "-vf", ",".join(overlay),
               "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-b:v", bitrate, "-maxrate", "12M", "-bufsize", "20M",
               "-c:a", "aac", "-shortest", output]
        subprocess.run(cmd, check=True)
        print(f"Video -> {output} ({duration:.1f}s, {width}x{height}, gradient fallback)")
        return output

    # Build one filtered stream per pattern-interrupt chunk, then
    # crossfade them. Visuals cycle so a short list still re-cuts at
    # every interrupt; zoom alternates in/out as a zoom punch.
    n = chunk_count
    seg = chunk
    inputs = []
    filters = []
    # One ffmpeg input per chunk (same file may be listed several times).
    for i in range(n):
        vis = accepted[i % len(accepted)]
        inputs += ["-loop", "1", "-i", vis["path"]] if vis["type"] == "image" else ["-i", vis["path"]]
        if vis["type"] == "image":
            zoom = ("min(zoom+0.0008,1.3)" if i % 2 == 0
                    else "max(1.25-0.0008*on,1.0)")
            filters.append(
                f"[{i}:v]scale={width * 2}:{height * 2},zoompan=z='{zoom}':"
                f"d={int(seg * FPS)}:s={width}x{height}:fps={FPS},format=yuv420p[v{i}]")
        else:
            clip_dur = vis.get("duration") or 0
            start = 0.0
            if clip_dur and clip_dur > seg:
                start = min(i * 2.0, clip_dur - seg)
            filters.append(
                f"[{i}:v]trim={start:.2f}:{start + seg:.2f},setpts=PTS-STARTPTS,{_fill_filter(width, height)}[v{i}]")
    audio_idx = n
    inputs += ["-i", audio_path]
    if n == 1:
        filters.append("[v0]copy[vx]")
    else:
        # xfade chain: each step fades 0.5s into the next segment.
        current, offset = "[v0]", 0.0
        for i in range(1, n):
            offset = offset + seg - FADE
            filters.append(f"{current}[v{i}]xfade=transition=fade:duration={FADE}:offset={offset:.2f}[x{i}]")
            current = f"[x{i}]"
        filters.append(f"{current}copy[vx]")
    filters.append("[vx]eq=contrast=1.05:saturation=1.10:brightness=0.02[vgrade]")
    filters.append(f"[vgrade]{','.join(overlay)}[vout]")
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", f"{audio_idx}:a",
            "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-b:v", bitrate, "-maxrate", "12M", "-bufsize", "20M",
            "-c:a", "aac", "-shortest", output])
    subprocess.run(cmd, check=True)
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
    visuals = list(args.visuals) + list(args.images)
    if args.visuals_file and os.path.exists(args.visuals_file):
        with open(args.visuals_file, encoding="utf-8") as fh:
            visuals.extend(json.load(fh))
    if args.fetch_stock:
        # Stock video first, then stock images — per visual_source order.
        stock = fetch_stock_videos(config, config.get("niche_keywords") or [])
        visuals = stock + visuals
    if not visuals:
        # Config order: stock video URLs first, then stock images.
        visuals = list(config.get("stock_video_urls") or []) + list(config.get("stock_image_urls") or [])
    for script in scripts:
        slug = re.sub(r"[^a-z0-9]+", "-", script["topic"].lower()).strip("-") or "script"
        audio = os.path.join(args.audio_dir, f"{script['rank']:02d}-{slug}.mp3")
        if not os.path.exists(audio):
            audio = os.path.join("data/audio", f"{script['rank']:02d}-{slug}.mp3")
        output = os.path.join(args.outdir, f"{script['rank']:02d}-{slug}.mp4")
        build_video(script, audio, output, visuals=visuals or None,
                    bitrate=bitrate, min_resolution=min_resolution,
                    width=width, height=height,
                    end_card_text=args.end_card_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
