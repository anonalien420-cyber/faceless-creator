"""Narrate scripts with the most human-sounding voice available, by tier.

Voice tiers (config: narrator_tier, default "free"):
- Tier 1, free — Edge TTS neural voices (en-US-ChristopherNeural /
  en-US-AriaNeural) with SSML prosody: slower rate on the hook, natural
  pauses at commas/periods, emphasis on hook words. This is the default
  and needs no key. It is the closest free option to a human voice, but
  no AI voice is indistinguishable from a human — do not claim it is.
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
neural synthesis (not concatenative/robotic TTS) + prosody (pitch/rate
variation) + pacing (real pauses, not a flat stream) + emphasis on the
words a human would stress. The "humanizing" pass below adds exactly
those three things on top of the base voice.

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
import tempfile

try:
    from src.config import load_config
except ImportError:
    from config import load_config

try:
    from src.pronunciation import apply_pronunciation, flag_unknown
except ImportError:  # running from inside src/
    try:
        from pronunciation import apply_pronunciation, flag_unknown
    except ImportError:  # dictionary support unavailable; narrate as written
        apply_pronunciation = flag_unknown = None

# Sane narration-speed bounds (production-readiness issue 5). Speeds
# outside this range are a config/CLI mistake, not a creative choice:
# below 0.5x the narration drags past every format's duration budget,
# above 2.0x it is unintelligible. Reject loudly, never clamp silently
# (a silent clamp would ship audio at a speed nobody asked for).
MIN_SPEED = 0.5
MAX_SPEED = 2.0

# Fallback marker: when a narration run uses a different engine/voice
# than configured, an entry is appended here so the pipeline (and a
# human) can see the run is degraded. One file per narration run:
# main() clears it at start, so it always describes the latest run.
NARRATION_FALLBACK_PATH = "data/narration_fallback.json"

_KOKORO_VOICE_RE = re.compile(r"^[ab][fm]_")
_KOKORO_USED_RE = re.compile(r"^kokoro \(([^)]+)\)")


def _expected_kokoro_voice(voice):
    """The Kokoro voice narrate_kokoro will actually use for `voice`:
    the configured voice when it looks like a Kokoro voice, else
    Kokoro's af_heart default (narrate_kokoro substitutes silently)."""
    return voice if _KOKORO_VOICE_RE.match(voice or "") else "af_heart"


def detect_narration_fallback(used, tier, voice):
    """Detect a narration fallback: the engine/voice actually used
    differs from what the tier + configured voice asked for.

    Returns {"fallback": bool, "expected_engine": str,
    "expected_voice": str|None, "used": str, "reason": str}.
    - tier "local": expects Kokoro with the configured voice
      (bm_george). Edge TTS, pyttsx3, or a different Kokoro voice
      is a fallback.
    - tier "free": expects Edge TTS. The pyttsx3 robotic fallback
      (or any other engine) is a fallback.
    - tier "paid": expects ElevenLabs. Anything else is a fallback.
    The "used" strings are the ones narrate_* return, so detection
    never depends on probing the audio after the fact.
    """
    used = used or ""
    tier = (tier or "free").lower()
    if tier == "local":
        expected_voice = _expected_kokoro_voice(voice)
        match = _KOKORO_USED_RE.match(used)
        if not match:
            return {"fallback": True, "expected_engine": "kokoro",
                    "expected_voice": expected_voice, "used": used,
                    "reason": "tier 'local' expects Kokoro voice "
                              f"{expected_voice}, but narration used "
                              f"{used or 'nothing'}"}
        if match.group(1) != expected_voice:
            return {"fallback": True, "expected_engine": "kokoro",
                    "expected_voice": expected_voice, "used": used,
                    "reason": f"Kokoro voice {match.group(1)} was used "
                              f"instead of configured {expected_voice}"}
        return {"fallback": False, "expected_engine": "kokoro",
                "expected_voice": expected_voice, "used": used,
                "reason": ""}
    if tier == "paid":
        if not used.startswith("elevenlabs"):
            return {"fallback": True, "expected_engine": "elevenlabs",
                    "expected_voice": None, "used": used,
                    "reason": "tier 'paid' expects ElevenLabs, but "
                              f"narration used {used or 'nothing'}"}
        return {"fallback": False, "expected_engine": "elevenlabs",
                "expected_voice": None, "used": used, "reason": ""}
    # tier "free": Edge TTS expected; the robotic pyttsx3 fallback
    # (or any other engine) is a fallback.
    if used.startswith("pyttsx3"):
        return {"fallback": True, "expected_engine": "edge-tts",
                "expected_voice": None, "used": used,
                "reason": "tier 'free' expects Edge TTS, but narration "
                          "fell back to the robotic pyttsx3 voice"}
    if not used.startswith("edge-tts"):
        return {"fallback": True, "expected_engine": "edge-tts",
                "expected_voice": None, "used": used,
                "reason": "tier 'free' expects Edge TTS, but narration "
                          f"used {used or 'nothing'}"}
    return {"fallback": False, "expected_engine": "edge-tts",
            "expected_voice": None, "used": used, "reason": ""}


def record_narration_fallback(detail, path=NARRATION_FALLBACK_PATH):
    """Append one fallback entry to the marker file (created if
    missing). The file describes the latest narration run only;
    main() clears it at start."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    entries = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                entries = json.load(fh)
            if not isinstance(entries, list):
                entries = []
        except (OSError, ValueError):
            entries = []
    from datetime import datetime, timezone
    entry = dict(detail)
    entry["at"] = datetime.now(timezone.utc).isoformat()
    entries.append(entry)
    try:
        from src.secrets import write_private_json
    except ImportError:
        from secrets import write_private_json
    write_private_json(path, entries)


def clear_narration_fallback(path=NARRATION_FALLBACK_PATH):
    try:
        os.remove(path)
    except OSError:
        pass


def validate_speed(speed):
    """Return float(speed) if it is a sane narration speed, else raise.

    Raises ValueError for non-numeric, non-finite, or out-of-range
    values, naming the allowed range.
    """
    try:
        value = float(speed)
    except (TypeError, ValueError):
        raise ValueError(
            "Invalid narration speed {!r}: must be a number between "
            "{} and {}.".format(speed, MIN_SPEED, MAX_SPEED)) from None
    import math
    if not math.isfinite(value) or not MIN_SPEED <= value <= MAX_SPEED:
        raise ValueError(
            "Invalid narration speed {}: must be between {} and {} "
            "(got {}).".format(speed, MIN_SPEED, MAX_SPEED, value))
    return value


def slug(text):
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "script"


def humanize_text(text, pause_ms=350, speed=1.0):
    """Return (ssml, plain_with_pauses) for one script.

    - First sentence (the hook) is emphasized.
    - Commas get a short break, sentence ends get the full pause.
    - Plain version uses extra punctuation spacing so even non-SSML
      engines get some pacing instead of a flat monotone stream.
    Plain-text pauses cover all sentence terminators (". ", "? ", "! ")
    and lead-in colons (": ") — the earlier version only paused after
    commas and periods, so consecutive questions (e.g. the closing
    "What do you think happened? What does the record actually
    support?") and colon lead-ins ("What remains unknown: ...") ran
    together with no beat. NOTE: those "..." markers only affect
    engines that read punctuation (Edge/pyttsx3). Kokoro ignores
    them — verified 2026-11-15 by an ellipsis probe (identical total
    durations, 6.70–6.90s, with and without "..." after a sentence).
    Real pacing control for Kokoro is the segment-silence mechanism
    in narrate_kokoro (sentence_pauses), not punctuation.
    """
    validate_speed(speed)
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sentences:
        return text, text
    hook, rest = sentences[0], sentences[1:]
    comma_pause = max(80, pause_ms // 2)
    ssml_parts = [f'<emphasis level="strong">{hook}</emphasis>']
    for sentence in rest:
        ssml_parts.append(sentence)
    ssml_body = " ".join(ssml_parts)
    # Breaks after commas and sentence ends (SSML only).
    ssml_body = re.sub(r",\s*", f',<break time="{comma_pause}ms"/> ', ssml_body)
    ssml_body = re.sub(r"([.!?])\s+",
                       f'\\1<break time="{pause_ms}ms"/> ', ssml_body)
    rate_pct = int(round(speed * 100))
    ssml = (f'<speak><prosody rate="{rate_pct}%" pitch="+1st">'
            f"{ssml_body}</prosody></speak>")
    plain = (text.replace(", ", ", ... ").replace(". ", ". ... ")
             .replace("? ", "? ... ").replace("! ", "! ... ")
             .replace(": ", ": ... "))
    return ssml, plain


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


def narrate_edge(text, voice, output, ssml, speed):
    """Edge TTS via its Python library if present (SSML), else CLI (plain)."""
    try:
        import edge_tts
        import asyncio
        communicate = edge_tts.Communicate(ssml, voice)
        asyncio.run(communicate.save(output))
        return "edge-tts (SSML prosody)"
    except ImportError:
        pass
    except Exception as exc:
        print(f"WARNING: edge-tts library SSML failed ({exc}); trying CLI.", file=sys.stderr)
    plain = text
    subprocess.run(
        ["edge-tts", "--voice", voice, "--file", output, "--text", plain],
        check=True,
    )
    return "edge-tts CLI (plain text, pause punctuation)"


def sentence_pauses(text, hook_pause=0.3, question_pause=0.2):
    """Return {sentence_index: extra_silence_seconds} for Kokoro.

    Two targeted beats, both measured against the 2026-11-15 Antikythera
    render (sentence-boundary gaps there were 0.48–0.78s):
    - After the hook (sentence 0): +hook_pause, so the opening claim
      lands before the story starts. The hook gap was the shortest in
      the render (0.48s).
    - Between consecutive closing questions ("What do you think
      happened? What does the record actually support?"): +question_pause,
      so the CTA breathes instead of running together.
    Only these two beats are lengthened; every other boundary keeps
    Kokoro's natural pause. Total added time is hook_pause +
    question_pause (0.5s by default) — inside the production duration
    budget (body ±2s, video ±1s).
    """
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    pauses = {}
    if len(sentences) >= 2 and hook_pause > 0:
        pauses[0] = hook_pause
    for i in range(len(sentences) - 1):
        if (sentences[i].rstrip().endswith("?")
                and sentences[i + 1].rstrip().endswith("?")
                and question_pause > 0):
            pauses[i] = pauses.get(i, 0.0) + question_pause
    return pauses


def narrate_kokoro(text, voice, output, speed):
    """Kokoro open-weight TTS (local, free). Voice names are Kokoro voices
    (e.g. af_heart, am_adam); the config voice is passed through only if
    it looks like a Kokoro voice, otherwise Kokoro's default is used.

    Single pipeline call over the whole text (the v1 behaviour). A
    per-sentence variant was tried 2026-11-16 and REVERTED: synthesizing
    sentence-by-sentence made Kokoro speak ~20% slower (the same 151
    words rendered as 80.4s instead of 63.0s, blowing the video
    duration budget), even though each call used the same voice and
    speed. Pacing beats are therefore added AFTER synthesis, by
    inserting silence at measured sentence boundaries — see
    insert_silence() — which keeps the proven single-call delivery
    exactly and makes each beat verifiable.
    """
    from kokoro import KPipeline
    import soundfile as sf
    validate_speed(speed)
    kokoro_voice = voice if re.match(r"^[ab][fm]_", voice or "") else "af_heart"
    # Kokoro's language pipeline must match the voice's accent: British
    # voices (bm_/bf_) use the British pipeline ("b"), American voices
    # (am_/af_) use the American one ("a"). Using "a" with a British
    # voice silently Americanises pronunciation, so derive it from the
    # resolved voice, not from a hardcoded default.
    lang = "b" if kokoro_voice.startswith("b") else "a"
    pipeline = KPipeline(lang_code=lang)
    audio_chunks = []
    for _, _, audio in pipeline(text, voice=kokoro_voice, speed=speed):
        audio_chunks.append(audio)
    if not audio_chunks:
        raise RuntimeError("Kokoro produced no audio")
    import numpy as np
    combined = np.concatenate(audio_chunks)
    sf.write(output, combined, 24000)
    return f"kokoro ({kokoro_voice})"


def insert_silence(audio_path, output_path, pauses, sample_rate=24000):
    """Insert exact digital silence into a narration file at chosen times.

    `pauses` is a list of (after_seconds, duration_seconds), sorted
    ascending — e.g. [(8.0, 0.3)] lengthens the pause after the word
    ending at 8.0s by 0.3s. The audio is decoded with ffmpeg to
    `sample_rate` mono PCM (Kokoro's native 24 kHz), silence is
    inserted at the given sample positions, and the result is written
    as mp3. Returns the new duration in seconds.

    This is the pacing mechanism for Kokoro: the "..." pause markers
    in the plain text are inert for Kokoro (ellipsis probe,
    2026-11-15), and per-sentence synthesis slows delivery (see
    narrate_kokoro), so beats are inserted here, at measured
    sentence-boundary times from a transcription of the rendered
    narration. Callers must shift their word timings by the inserted
    amounts (each word after an insertion moves later by the sum of
    all insertions before it).
    """
    import subprocess
    import numpy as np
    import soundfile as sf
    if not pauses:
        raise ValueError("insert_silence called with no pauses")
    pauses = sorted((float(t), float(d)) for t, d in pauses)
    if any(d <= 0 for _, d in pauses):
        raise ValueError("pause durations must be positive")
    with tempfile.TemporaryDirectory(prefix="deep_scan_pacing_") as tmp:
        wav_in = os.path.join(tmp, "in.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-i", audio_path,
                        "-ac", "1", "-ar", str(sample_rate),
                        "-f", "wav", wav_in],
                       check=True)
        audio, sr = sf.read(wav_in, dtype="float32")
        if audio.ndim > 1:
            audio = audio[:, 0]
        # Insert from the END backwards so earlier sample positions
        # stay valid as later insertions shift the tail.
        pieces = []
        prev = len(audio)
        for after, dur in reversed(pauses):
            idx = min(int(round(after * sr)), len(audio))
            pieces.append(audio[idx:prev])
            pieces.append(np.zeros(int(round(dur * sr)), dtype=np.float32))
            prev = idx
        pieces.append(audio[:prev])
        combined = np.concatenate(list(reversed(pieces)))
        wav_out = os.path.join(tmp, "out.wav")
        sf.write(wav_out, combined, sr)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav_out,
                        "-codec:a", "libmp3lame", "-b:a", "64k", output_path],
                       check=True)
    return len(combined) / sr


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
        from src.secrets import redact, write_private_json
    except ImportError:
        from secrets import redact, write_private_json
    try:
        path = "data/run_log.json"
        log = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                log = json.load(fh)
        log.setdefault("steps", []).append(
            {"step": step, "detail": redact(detail)})
        os.makedirs("data", exist_ok=True)
        write_private_json(path, log)
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
    parser.add_argument("--pronunciation-dictionary", default="",
                        help="Path to data/pronunciation_dictionary.json "
                             "(default: the repo's dictionary). The "
                             "dictionary is applied in memory only, to the "
                             "text fed to TTS — scripts, ledger and subtitles "
                             "keep the correct written forms. If the file is "
                             "missing, narration proceeds as written with a "
                             "warning.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    voice = args.voice or config.get("narrator_voice", "en-US-ChristopherNeural")
    tier = (args.tier or config.get("narrator_tier", "free") or "free").lower()
    # Strict mode: any fallback fails the run instead of shipping the
    # wrong voice. Off by default (config narrator_strict, or the
    # DEEP_SCAN_STRICT_NARRATION=1 env override): a fallback is
    # logged loudly and marked degraded, but the run continues.
    strict = bool(config.get("narrator_strict")) or (
        os.environ.get("DEEP_SCAN_STRICT_NARRATION", "") == "1")
    # The fallback marker describes the latest narration run only.
    clear_narration_fallback()
    try:
        speed = validate_speed(
            args.speed or float(config.get("narrator_speed", 1.0) or 1.0))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    pause_ms = args.pause_ms or int(config.get("narrator_pause_ms", 350) or 350)
    with open(args.input, encoding="utf-8") as fh:
        scripts = json.load(fh)
    os.makedirs(args.outdir, exist_ok=True)
    for script in scripts:
        output = os.path.join(args.outdir, f"{script['rank']:02d}-{slug(script['topic'])}.mp3")
        # Pronunciation dictionary (in-memory only): verified respellings
        # are substituted into the TTS input so names come out right;
        # the written script, ledger and subtitles are untouched.
        spoken_text = script["text"]
        if apply_pronunciation is not None:
            try:
                dict_path = args.pronunciation_dictionary or None
                dictionary = None
                if dict_path:
                    import json as _json
                    with open(dict_path, encoding="utf-8") as _fh:
                        dictionary = _json.load(_fh)
                spoken_text, applied = apply_pronunciation(
                    script["text"], dictionary)
                unknown = flag_unknown(script["text"], dictionary)
                if applied:
                    print(f"Pronunciation respellings applied "
                          f"({script['topic']}): {', '.join(applied)}")
                if unknown:
                    print(f"NOTE: unverified pronunciations in "
                          f"'{script['topic']}': {', '.join(unknown)} "
                          f"(spoken as written; no respelling applied)")
            except FileNotFoundError:
                print("WARNING: pronunciation dictionary not found; "
                      "narrating as written.", file=sys.stderr)
        ssml, plain = humanize_text(spoken_text, pause_ms=pause_ms, speed=speed)
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
                    used = narrate_edge(plain, voice, output, ssml, speed)
            else:  # free (default): Edge TTS neural voice + SSML prosody
                if shutil.which("edge-tts"):
                    used = narrate_edge(plain, voice, output, ssml, speed)
                else:
                    try:
                        import edge_tts  # noqa: F401 — library path, no CLI needed
                        used = narrate_edge(plain, voice, output, ssml, speed)
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
        # Fallback detection (Phase 3): the voice actually used must
        # match the configured tier/voice. A fallback is never silent:
        # it is logged loudly, written to the marker file (so the
        # pipeline marks the run degraded), and fails the run outright
        # in strict mode.
        fallback = detect_narration_fallback(used, tier, voice)
        if fallback["fallback"]:
            print(f"WARNING: NARRATION FALLBACK DETECTED for "
                  f"{script['topic']}: {fallback['reason']}. The "
                  f"rendered voice is NOT the configured one.",
                  file=sys.stderr)
            record_narration_fallback(
                {"topic": script["topic"], "tier": tier,
                 "voice": voice, **fallback})
            if strict:
                print("ERROR: narrator_strict is set — refusing to ship "
                      "a fallback voice. Install Kokoro / Edge TTS for "
                      "the configured tier and re-run.", file=sys.stderr)
                return 1
        if not _check_audio(output, script["topic"]):
            return 1
        detail = {"voice": voice, "tier": tier, "used": used,
                  "fallback": fallback,
                  "speed": speed, "pause_ms": pause_ms}
        append_run_log(f"narrate:{script['topic']}", detail)
        print(f"Narrated -> {output} [{used}, tier={tier}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
