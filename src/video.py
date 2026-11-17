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

try:
    from src.job_state import persist_diagnostic
except ImportError:
    from job_state import persist_diagnostic

WIDTH, HEIGHT, FPS = 1080, 1920, 30
FADE = 0.5  # seconds of crossfade between visual segments


def _run_ffmpeg(cmd, step=None):
    """Run FFmpeg and preserve its diagnostic output on failure.

    The COMPLETE stderr (or stdout, if stderr is empty) is persisted
    verbatim to a file artifact
    (data/ffmpeg_diagnostics/<step>-<timestamp>.log, overridable via
    DEEP_SCAN_FFMPEG_DIAGNOSTICS_DIR) and the artifact path is named
    in the raised error. The message itself keeps only the last
    12,000 chars for readability — the full text is never discarded.
    `step` labels the artifact; when omitted it is derived from the
    output file (last argv element).
    """
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raw = result.stderr or result.stdout or "FFmpeg returned no diagnostic output"
        details = raw.strip()
        label = step
        if not label and cmd:
            label = os.path.splitext(os.path.basename(str(cmd[-1])))[0]
        try:
            artifact = persist_diagnostic(label or "ffmpeg", raw)
        except OSError:
            artifact = None
        tail = details[-12000:]
        if artifact:
            raise RuntimeError(
                f"FFmpeg failed with exit code {result.returncode}:\n"
                f"full diagnostic saved to {artifact}\n{tail}")
        raise RuntimeError(
            f"FFmpeg failed with exit code {result.returncode}:\n{tail}")
    return result


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


def _norm_token(word):
    """Lowercased alphanumeric form of a word for comparison."""
    return re.sub(r"[^a-z0-9]", "", word.lower())


_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
         "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1000000}


def _number_value(word):
    """Numeric value of a number word or a digit token, else None.

    Used to align script words with ASR tokens: the script says
    "two thousand" where the transcript hears the digits "2,000".
    """
    norm = _norm_token(word)
    if norm.isdigit():
        return int(norm)
    if norm in _ONES:
        return _ONES[norm]
    if norm in _TENS:
        return _TENS[norm]
    if norm in _SCALES:
        return _SCALES[norm]
    return None


def _canonical_tokens(words):
    """Collapse a word list into canonical tokens for alignment.

    Consecutive number words ("two", "thousand") collapse into one
    integer token (2000); every other word becomes its normalized
    string. Returns (tokens, spans) where spans[i] is the list of
    original word indices covered by tokens[i].
    """
    tokens, spans = [], []
    i = 0
    while i < len(words):
        value = _number_value(words[i])
        if value is not None:
            # Accumulate a number phrase: "two thousand" -> 2000,
            # "one hundred" -> 100. Standard small-number algorithm.
            total, current = 0, 0
            start = i
            while i < len(words):
                value = _number_value(words[i])
                if value is None:
                    break
                if value in (100, 1000, 1000000):
                    current = (current or 1) * value
                    if value >= 1000:
                        total += current
                        current = 0
                else:
                    current += value
                i += 1
            tokens.append(total + current)
            spans.append(list(range(start, i)))
        else:
            tokens.append(_norm_token(words[i]))
            spans.append([i])
            i += 1
    return tokens, spans


def align_script_to_timings(script_words, timed):
    """Assign a (start, end) to every script word from ASR word timings.

    `timed` is a list of (start, end, word) triples from a transcription
    of the actual spoken narration. The script words are the correct
    written forms; the timings are the spoken reality. Alignment is by
    difflib on canonical tokens (numbers collapse, so "two thousand"
    aligns with "2,000"), and mismatched blocks (e.g. a name the ASR
    misheard) share the block's timed span evenly. Returns a list of
    (start, end, script_word) triples in script order.
    """
    import difflib
    if not script_words or not timed:
        return []
    script_tokens, script_spans = _canonical_tokens(script_words)
    timed_words = [w for _, _, w in timed]
    timed_tokens, timed_spans = _canonical_tokens(timed_words)
    # Timed tokens are already merged digit groups ("2,000" -> 2000);
    # _canonical_tokens handles them because _number_value reads digits.
    matcher = difflib.SequenceMatcher(a=script_tokens, b=timed_tokens,
                                      autojunk=False)
    result = [None] * len(script_words)

    def timed_span(first, last):
        """(start, end) covering timed canonical tokens first..last."""
        if first > last:
            return None
        start = timed[timed_spans[first][0]][0]
        end = timed[timed_spans[last][-1]][1]
        return (start, end)

    def fill(script_lo, script_hi, span):
        """Split `span` evenly across script words script_lo..script_hi."""
        if span is None:
            return
        start, end = span
        count = script_hi - script_lo
        if count <= 0:
            return
        per = (end - start) / count
        for k in range(count):
            result[script_lo + k] = (start + k * per, start + (k + 1) * per)

    last_end = 0.0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for a, b in zip(range(i1, i2), range(j1, j2)):
                span = timed_span(b, b)
                fill(script_spans[a][0],
                     script_spans[a][-1] + 1, span)
                last_end = span[1]
        elif tag == "replace":
            span = timed_span(j1, j2 - 1)
            words_lo = script_spans[i1][0]
            words_hi = script_spans[i2 - 1][-1] + 1
            fill(words_lo, words_hi, span)
            if span:
                last_end = span[1]
        elif tag == "delete":
            # Script words the ASR did not emit: give them the gap
            # between the neighbouring timed tokens.
            words_lo = script_spans[i1][0]
            words_hi = script_spans[i2 - 1][-1] + 1
            next_start = (timed[timed_spans[j1][0]][0]
                          if j1 < len(timed_spans) else last_end + 0.3)
            fill(words_lo, words_hi, (last_end, next_start))
        # "insert": extra ASR tokens with no script word — ignore them.
    # Any word still unassigned (should not happen) gets the last end.
    for idx, entry in enumerate(result):
        if entry is None:
            result[idx] = (last_end, last_end + 0.2)
    return [(result[i][0], result[i][1], script_words[i])
            for i in range(len(script_words))]


def make_ass(script_text, duration, path, width=1080, height=1920, fontsize=72,
             word_timings=None, extra_captions=None):
    """Write an .ass subtitle file.

    Without word_timings (legacy callers): uniform 7-word chunks
    evenly spaced over `duration`, as before.
    With word_timings — a list of (start, end, word) from a
    transcription of the actual spoken narration — captions follow the
    spoken words under the kinetic typography preset: at most 3 words
    per frame, UPPERCASE, DejaVu Sans Bold (the Montserrat-Black
    mapping). The caption TEXT always comes from the script (correct
    written forms); only the TIMING comes from the transcription.
    `extra_captions` is a list of (start, end, text) appended after
    the body captions (e.g. the subscribe close, rendered as a
    separate clip after the body).
    """
    if word_timings:
        aligned = align_script_to_timings(script_text.split(), word_timings)
        chunks = []
        frame = []
        for start, end, word in aligned:
            frame.append((start, end, word))
            if len(frame) >= 3:
                chunks.append(frame)
                frame = []
        if frame:
            chunks.append(frame)
        timed_chunks = []
        for frame in chunks:
            start = max(0.0, frame[0][0] - 0.03)
            end = frame[-1][1] + 0.05
            text = " ".join(w for _, _, w in frame).upper()
            timed_chunks.append((start, end, text))
        # Clamp overlaps: a frame must end before the next one starts.
        for i in range(len(timed_chunks) - 1):
            start, end, text = timed_chunks[i]
            next_start = timed_chunks[i + 1][0]
            if end > next_start - 0.01:
                timed_chunks[i] = (start, next_start - 0.01, text)
        chunks = [(s, e, t) for (s, e, t) in timed_chunks]
    else:
        words = script_text.split()
        raw, chunk = [], []
        for word in words:
            chunk.append(word)
            if len(chunk) >= 7:
                raw.append(" ".join(chunk))
                chunk = []
        if chunk:
            raw.append(" ".join(chunk))
        per = duration / max(len(raw), 1)
        chunks = [(i * per, (i + 1) * per, text)
                  for i, text in enumerate(raw)]
    if extra_captions:
        chunks.extend((float(s), float(e), str(t))
                      for (s, e, t) in extra_captions)
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
             "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, "
             "Alignment, MarginL, MarginR, MarginV, BorderStyle, Outline",
             f"Style: Default,DejaVu Sans,{fontsize},&H00FFFFFF,&H80000000,-1,2,60,60,400,1,5",
             "", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for start, end, text in chunks:
        def fmt(t):
            h, rem = divmod(int(t), 3600)
            m, s = divmod(rem, 60)
            return f"{h}:{m:02d}:{s:02d}.{int((t % 1) * 100):02d}"
        safe = text.replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{fmt(start)},{fmt(end)},Default,,0,0,0,,{safe}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def _fit_fontsize(text, max_width, start_size, font_name="DejaVuSans-Bold.ttf"):
    """Largest fontsize <= start_size whose rendered width fits max_width.

    Found 2026-11-15 on the first real Antikythera run: the title card
    drew the 45-character topic at 72pt, wider than the 1080px frame,
    so the title was cut off at both edges in the first 3 seconds.
    Measured with Pillow when available (Bold metrics are wider than
    the regular face drawtext uses, so the fit is conservative);
    otherwise falls back to a ~0.62em average-glyph-width estimate.
    """
    try:
        from PIL import ImageFont
        size = start_size
        while size > 8:
            if ImageFont.truetype(font_name, size).getlength(text) <= max_width:
                return size
            size -= 2
        return size
    except Exception:
        return max(8, min(start_size,
                          int(max_width / max(1, len(text) * 0.62))))


def _write_drawtext_file(directory, name, text):
    """Write arbitrary text for FFmpeg drawtext without filtergraph quoting."""
    path = os.path.join(directory, f"{name}.txt")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(str(text))
    return path


def _drawtext_path(path):
    """Escape a generated path for FFmpeg's filter option parser."""
    return path.replace("\\", "\\\\").replace(":", "\\:")


def _fill_filter(width, height):
    """Scale to fill WxH and crop, preserving aspect (no stretch, no bars)."""
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps=30,format=yuv420p")


def _normalize_rendered_audio(output):
    """Loudness-normalize a rendered MP4 in place (fail-soft).

    The video stream is copied untouched; only the audio is
    re-encoded to the -14 LUFS / -1 dBTP master (see src/music.py).
    A failure here must never break the render itself — the QA
    loudness gate is the fail-loud layer that refuses a quiet video.
    """
    try:
        from src.music import normalize_loudness
    except ImportError:
        from music import normalize_loudness
    if not os.path.exists(output):
        return  # mocked / failed render left no file; nothing to normalize
    tmp = output + ".loudnorm.mp4"
    try:
        report = normalize_loudness(output, tmp)
        os.replace(tmp, output)
        out = report["output_measured"]
        print(f"Loudness normalized -> {output} "
              f"({out['input_i']:.2f} LUFS, {out['input_tp']:.2f} dBTP)")
    except Exception as exc:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        print(f"WARNING: loudness normalization failed ({exc}); "
              f"keeping un-normalized render {output}", file=sys.stderr)


def build_video(script, audio_path, output, visuals=None, duration=None,
                bitrate="10M", min_resolution=1080, width=1080, height=1920,
                end_card_text="Subscribe for the next one",
                word_timings=None, normalize_loudness=True):
    """Render one video. Shorts default 1080x1920; long-form 1920x1080.

    `script` is a dict with text/topic/hook (see script.py). Captions are
    written to output + ".ass" (QA also checks that path).

    `word_timings` (optional): a list of (start, end, word) triples from
    a transcription of the ACTUAL narration audio. When given, captions
    follow the spoken words (see align_script_to_timings); when omitted
    the legacy uniform chunking is used, so existing callers are
    unaffected.

    `normalize_loudness` (default True): after rendering, normalize
    the finished MP4's audio to -14 LUFS / -1 dBTP (video stream
    copied untouched). Fail-soft — a normalization failure only warns
    and the un-normalized render is kept; the QA loudness gate is
    what refuses a quiet video. Pass False only for tests that need
    the raw render.

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
             fontsize=fontsize, word_timings=word_timings)
    drawtext_dir = tempfile.mkdtemp(prefix="deep_scan_drawtext_")
    title = _write_drawtext_file(drawtext_dir, "title", script["topic"].title()[:60])
    hook_text = (script.get("hook", "") or "").split(". ")[0][:80]
    hook_line = (_write_drawtext_file(drawtext_dir, "hook", hook_text)
                 if hook_text else "")
    accepted, _rejected = resolve_visuals(visuals or [], min_resolution)
    # Pattern-interrupt interval: 25s longs, 10s Shorts.
    interrupt = 25.0 if width > height else 10.0
    import math as _math
    chunk_count = max(1, _math.ceil(duration / interrupt))
    # xfade overlap fix (found 2026-11-15 on the first real Antikythera
    # run): joining n segments of `chunk` with (n-1) fades of FADE
    # produces n*chunk - (n-1)*FADE seconds of video, NOT n*chunk.
    # With chunk = duration / chunk_count the joined video came out
    # (n-1)*FADE short (63.03s of narration rendered as a 60.03s
    # video) and `-shortest` cut the tail of the narration off.
    # Lengthen each segment so the joined video is exactly `duration`.
    chunk = ((duration + (chunk_count - 1) * FADE) / chunk_count
             if chunk_count > 1 else duration)
    # Dynamic text is read from files with expansion disabled.
    title_text = script["topic"].title()[:60]
    title_size = _fit_fontsize(title_text, width - 80, fontsize)
    overlay = [
        f"drawbox=x=0:y={height - 50}:w='{width}*t/{duration:.2f}':h=12:color=yellow@0.9:t=fill",
        f"drawtext=textfile={_drawtext_path(title)}:expansion=none:font=DejaVu Sans:fontsize={title_size}:fontcolor=white:"
        f"borderw=3:bordercolor=black:x=(w-text_w)/2:y=200:enable='lt(t,3)'",
        f"ass={ass_path}",
    ]
    if hook_line:
        overlay.append(
            f"drawtext=textfile={_drawtext_path(hook_line)}:expansion=none:font=DejaVu Sans:fontsize={max(28, fontsize - 18)}:"
            f"fontcolor=white:borderw=2:bordercolor=black:x=(w-text_w)/2:"
            f"y={200 + fontsize + 20}:enable='lt(t,5)'")
    prompts = ["The key part:", "Here's why it works:", "Don't miss this:", "Quick check:"]
    for k in range(1, chunk_count):
        t = k * chunk
        prompt_file = _write_drawtext_file(
            drawtext_dir, f"prompt_{k}", prompts[(k - 1) % len(prompts)])
        overlay.append(
            f"drawtext=textfile={_drawtext_path(prompt_file)}:expansion=none:font=DejaVu Sans:fontsize={max(32, fontsize - 14)}:"
            f"fontcolor=yellow:borderw=3:bordercolor=black:x=(w-text_w)/2:"
            f"y={height // 3}:enable='between(t,{t:.2f},{t + 2:.2f})'")
    end_card = _write_drawtext_file(drawtext_dir, "end_card", end_card_text)
    overlay.append(
        f"drawtext=textfile={_drawtext_path(end_card)}:expansion=none:font=DejaVu Sans:"
        f"fontsize={fontsize}:fontcolor=white:borderw=3:bordercolor=black:"
        f"x=(w-text_w)/2:y={height - 220}:enable='gt(t,{duration - 3:.2f})'")
    if not accepted:
        # Animated gradient fallback (no asset to grade).
        # NOTE: the lavfi gradients source defaults to 25 fps, but the
        # QA gate requires 30 fps — pin the chain to 30 explicitly, the
        # same rate the visuals path enforces with fps={FPS}.
        cmd = ["ffmpeg", "-y", "-f", "lavfi",
               "-i", f"gradients=s={width}x{height}:c0=0x0f172a:c1=0x1e3a8a:x0=0:y0=0:x1={width}:y1={height}:duration={duration}",
               "-i", audio_path, "-vf", ",".join(["fps=30"] + overlay),
               "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-b:v", bitrate, "-maxrate", "12M", "-bufsize", "20M",
               "-c:a", "aac", "-shortest", output]
        try:
            _run_ffmpeg(cmd)
        finally:
            shutil.rmtree(drawtext_dir, ignore_errors=True)
        if normalize_loudness:
            _normalize_rendered_audio(output)
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
           ["-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", f"{audio_idx}:a",
            "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-b:v", bitrate, "-maxrate", "12M", "-bufsize", "20M",
            "-c:a", "aac", "-shortest", output])
    try:
        _run_ffmpeg(cmd)
    finally:
        shutil.rmtree(drawtext_dir, ignore_errors=True)
    if normalize_loudness:
        _normalize_rendered_audio(output)
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
    parser.add_argument("--word-timings", default="",
                        help="JSON file of [start, end, word] triples from a "
                        "transcription of the narration audio; captions are "
                        "timed to the spoken words instead of uniform "
                        "chunking. Applies to every script in --input.")
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
    topic_visuals = {}
    if args.visuals_file and os.path.exists(args.visuals_file):
        with open(args.visuals_file, encoding="utf-8") as fh:
            loaded_visuals = json.load(fh)
        if isinstance(loaded_visuals, dict) and isinstance(loaded_visuals.get("by_topic"), dict):
            topic_visuals = loaded_visuals["by_topic"]
        elif isinstance(loaded_visuals, list):
            visuals.extend(loaded_visuals)
    if args.fetch_stock:
        # Stock video first, then stock images — per visual_source order.
        stock = fetch_stock_videos(config, config.get("niche_keywords") or [])
        visuals = stock + visuals
    if not visuals:
        # Config order: stock video URLs first, then stock images.
        visuals = list(config.get("stock_video_urls") or []) + list(config.get("stock_image_urls") or [])
    word_timings = None
    if args.word_timings:
        with open(args.word_timings, encoding="utf-8") as fh:
            word_timings = [(float(s), float(e), str(w))
                            for s, e, w in json.load(fh)]
    for script in scripts:
        slug = re.sub(r"[^a-z0-9]+", "-", script["topic"].lower()).strip("-") or "script"
        audio = os.path.join(args.audio_dir, f"{script['rank']:02d}-{slug}.mp3")
        if not os.path.exists(audio):
            audio = os.path.join("data/audio", f"{script['rank']:02d}-{slug}.mp3")
        output = os.path.join(args.outdir, f"{script['rank']:02d}-{slug}.mp4")
        selected_visuals = topic_visuals.get(script.get("topic"), visuals)
        build_video(script, audio, output, visuals=selected_visuals or None,
                    bitrate=bitrate, min_resolution=min_resolution,
                    width=width, height=height,
                    end_card_text=args.end_card_text,
                    word_timings=word_timings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
