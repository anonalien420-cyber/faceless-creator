"""Narrate scripts with the most human-sounding voice available, by tier.

Voice tiers (config: narrator_tier, default "free"):
- Tier 1, free — Edge TTS neural voices (en-US-ChristopherNeural /
  en-US-AriaNeural) with a configurable speaking rate and punctuation
  pacing (short beats at commas, longer ones at sentence ends). edge-tts
  does not accept custom SSML, so rate is set via its rate parameter, not
  markup. This is the default and needs no key. It is the closest free
  option to a human voice, but no AI voice is indistinguishable from a
  human — do not claim it is.
- Tier 2, free/local — Kokoro (open-weight, often more natural than
  Edge TTS) if installed (`pip install kokoro`). If Kokoro is not
  installed, this tier falls back to Edge TTS with a warning, because
  shipping narration matters more than failing on a missing optional
  package. Explicit `local` tier + missing Kokoro still falls back;
  see README for install steps.
- Tier 3, optional paid — ElevenLabs (or PlayHT-style) when an API key
  is set (ELEVENLABS_API_KEY env var). Never required, never default.
  If tier "paid" is requested but no key is set, this FAILS loudly
  rather than silently downgrading — a paid tier was an explicit choice.

Why some voices sound more human (README expands on this):
neural synthesis (not concatenative/robotic TTS) + a natural speaking
rate + pacing (real pauses, not a flat stream). The "humanizing" pass
below adds punctuation pacing on top of the base voice, and the rate
parameter sets the overall speed.

Safety: after narration, the output file is checked — it must exist,
be non-trivial in size, and (when ffprobe is available) have a
duration > 0. Silence/empty audio fails loudly; a silent video must
never be shipped and called narrated.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

try:
    from src.config import load_config
except ImportError:
    from config import load_config


def slug(text):
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "script"


def humanize_text(text, pause_ms=350):
    """Return plain text with pacing punctuation for natural delivery.

    edge-tts does NOT accept custom SSML — it XML-escapes its input, so
    sending <speak>/<break> tags would make the voice read the tag words
    aloud. Prosody is therefore applied two ways that actually work:
    speaking rate via the engine's rate parameter (see narrate_edge), and
    pacing via punctuation — commas get a short beat, sentence ends a
    longer one. The number of pause dots scales with pause_ms.
    """
    beat = "." * max(1, min(6, int(pause_ms // 100)))
    plain = text.replace(", ", ", " + beat + " ")
    plain = re.sub(r"([.!?])\s+", r"\1 " + beat + " ", plain)
    return plain


def _check_audio(path, label):
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        print(f"ERROR: Narration for {label} is empty or missing ({path}). "
              "Refusing to ship silent audio.", file=sys.stderr)
        return False
    if shutil.which("ffprobe"):
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, check=True)
            if float(out.stdout.strip()) <= 0:
                print(f"ERROR: Narration for {label} has zero duration.", file=sys.stderr)
                return False
        except Exception:
            pass  # size check already passed; duration check is best-effort
    return True


def _srt_to_timings(srt_path, timings_path):
    """Convert an edge-tts CLI SRT (sentence cues) into the timings sidecar
    format video.py understands. Used when the library path is unavailable."""
    import json
    cues = []
    try:
        with open(srt_path, encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        time_line = next((ln for ln in lines if "-->" in ln), "")
        text_lines = [ln for ln in lines if "-->" not in ln and not ln.strip().isdigit()]
        if not time_line or not text_lines:
            continue
        try:
            start_s, end_s = time_line.split("-->")
            cues.append({"text": " ".join(text_lines).strip(),
                         "start": _srt_seconds(start_s), "end": _srt_seconds(end_s)})
        except ValueError:
            continue
    if cues:
        with open(timings_path, "w", encoding="utf-8") as fh:
            json.dump({"sentences": cues}, fh)


def _srt_seconds(value):
    value = value.strip().replace(",", ".")
    h, m, s = value.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def narrate_edge(text, voice, output, speed):
    """Edge TTS neural voice via the library, else the CLI.

    Pass plain (paced) text — never SSML — and apply the configured
    speaking rate through the rate parameter. The library path streams
    WordBoundary metadata and writes a <output>.timings.json sidecar so
    video.py can render accurate, word-highlighted captions. The CLI
    fallback writes SRT sentence cues and converts them to the same
    sidecar. The CLI writes audio with --write-media (--file is an INPUT
    flag, not an output flag).
    """
    rate = f"{int(round((speed - 1.0) * 100)):+d}%"
    timings_path = output + ".timings.json"
    try:
        import asyncio

        import edge_tts

        async def _run():
            communicate = edge_tts.Communicate(text, voice, rate=rate,
                                               boundary="WordBoundary")
            words = []
            with open(output, "wb") as audio:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        # Offsets/durations are 100-nanosecond ticks.
                        words.append({"text": chunk["text"],
                                      "start": chunk["offset"] / 1e7,
                                      "end": (chunk["offset"] + chunk["duration"]) / 1e7})
            return words

        words = asyncio.run(_run())
        if words:
            with open(timings_path, "w", encoding="utf-8") as fh:
                json.dump({"words": words}, fh)
        return f"edge-tts (rate {rate}, word timings)"
    except ImportError:
        pass
    except Exception as exc:
        print(f"WARNING: edge-tts library failed ({exc}); trying CLI.", file=sys.stderr)
    srt_path = output + ".srt"
    subprocess.run(
        ["edge-tts", "--voice", voice, "--text", text, "--rate", rate,
         "--write-media", output, "--write-subtitles", srt_path],
        check=True,
    )
    _srt_to_timings(srt_path, timings_path)
    return f"edge-tts CLI (rate {rate}, sentence timings)"


def narrate_kokoro(text, voice, output, speed):
    """Kokoro open-weight TTS (local, free). Voice names are Kokoro voices
    (e.g. af_heart, am_adam); the config voice is passed through only if
    it looks like a Kokoro voice, otherwise Kokoro's default is used."""
    import soundfile as sf
    from kokoro import KPipeline
    lang = "a"  # American English
    pipeline = KPipeline(lang_code=lang)
    kokoro_voice = voice if re.match(r"^[ab][fm]_", voice or "") else "af_heart"
    audio_chunks = []
    for _, _, audio in pipeline(text, voice=kokoro_voice, speed=speed):
        audio_chunks.append(audio)
    if not audio_chunks:
        raise RuntimeError("Kokoro produced no audio")
    import numpy as np
    combined = np.concatenate(audio_chunks)
    sf.write(output, combined, 24000)
    return f"kokoro ({kokoro_voice})"


def narrate_elevenlabs(text, voice, output):
    """ElevenLabs paid TTS. Requires ELEVENLABS_API_KEY; never default."""
    import urllib.request
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise RuntimeError(
            "narrator_tier='paid' but ELEVENLABS_API_KEY is not set. "
            "Set the key or switch narrator_tier back to 'free'.")
    voice_id = voice if re.match(r"^[A-Za-z0-9]{20}$", voice or "") else "21m00Tcm4TlvDq8ikWAM"
    body = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75,
                           "style": 0.3, "use_speaker_boost": True},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        data=body, method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(output, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    return f"elevenlabs ({voice_id})"


def append_run_log(step, detail):
    try:
        path = "data/run_log.json"
        log = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                log = json.load(fh)
        log.setdefault("steps", []).append({"step": step, "detail": detail})
        os.makedirs("data", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
    except Exception as exc:
        print(f"WARNING: could not append to run log ({exc})", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/scripts.json")
    parser.add_argument("--outdir", default="data/audio")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--voice", default="")
    parser.add_argument("--tier", default="")
    parser.add_argument("--speed", type=float, default=0.0)
    parser.add_argument("--pause-ms", type=int, default=0)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    voice = args.voice or config.get("narrator_voice", "en-US-ChristopherNeural")
    tier = (args.tier or config.get("narrator_tier", "free") or "free").lower()
    speed = args.speed or float(config.get("narrator_speed", 1.0) or 1.0)
    pause_ms = args.pause_ms or int(config.get("narrator_pause_ms", 350) or 350)
    with open(args.input, encoding="utf-8") as fh:
        scripts = json.load(fh)
    os.makedirs(args.outdir, exist_ok=True)
    try:
        from src import cache
    except ImportError:
        import cache
    cache_enabled = bool(config.get("cache_enabled", True))
    for script in scripts:
        output = os.path.join(args.outdir, f"{script['rank']:02d}-{slug(script['topic'])}.mp3")
        # Cache: skip re-TTS when the script text + voice settings are
        # unchanged (the timings sidecar is cached alongside the audio).
        key = cache.make_key(script["text"], voice, tier, speed, pause_ms)
        if cache_enabled and cache.is_cached("narration", key, output):
            print(f"Narrated -> {output} (cached, unchanged script/voice)")
            append_run_log(f"narrate:{script['topic']}",
                           {"voice": voice, "tier": tier, "used": "cached",
                            "speed": speed, "pause_ms": pause_ms})
            continue
        plain = humanize_text(script["text"], pause_ms=pause_ms)
        used = ""
        try:
            if tier == "paid":
                # Paid tier is explicit: no silent downgrade on missing key.
                used = narrate_elevenlabs(plain, voice, output)
            elif tier == "local":
                try:
                    used = narrate_kokoro(plain, voice, output, speed)
                except ImportError:
                    print("WARNING: Kokoro not installed; falling back to Edge TTS "
                          "(pip install kokoro for the local tier).", file=sys.stderr)
                    used = narrate_edge(plain, voice, output, speed)
            else:  # free (default): Edge TTS neural voice + rate/pacing
                if shutil.which("edge-tts"):
                    used = narrate_edge(plain, voice, output, speed)
                else:
                    try:
                        import edge_tts  # noqa: F401 — library path, no CLI needed
                        used = narrate_edge(plain, voice, output, speed)
                    except ImportError:
                        print("WARNING: edge-tts not found; trying pyttsx3 fallback.", file=sys.stderr)
                        import pyttsx3
                        engine = pyttsx3.init()
                        engine.save_to_file(plain, output)
                        engine.runAndWait()
                        used = "pyttsx3 (robotic fallback — install edge-tts for a natural voice)"
        except Exception as exc:
            print(f"ERROR: Narration failed for {script['topic']}: {exc}", file=sys.stderr)
            return 1
        if not _check_audio(output, script["topic"]):
            return 1
        detail = {"voice": voice, "tier": tier, "used": used,
                  "speed": speed, "pause_ms": pause_ms}
        append_run_log(f"narrate:{script['topic']}", detail)
        if cache_enabled:
            cache.mark_cached("narration", key, output)
        print(f"Narrated -> {output} [{used}, tier={tier}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
