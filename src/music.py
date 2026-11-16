"""Select and mix a music bed that MATCHES what's trending — in style only.

How it works (see also README.md):
1. trends.py builds a "trending audio profile" from the top 5 videos:
   most common genre + median tempo (BPM) + dominant mood. That profile
   comes only from audio fields a source or manual input actually
   reported (trending_audio / audio_genre / audio_tempo_bpm / audio_mood).
   Nothing is claimed trending without a source entry.
2. This module scores every track in config `music_library` against that
   profile (genre match, mood match, tempo closeness) and picks the best
   match. It then mixes that track under the narration at low volume.

COPYRIGHT RULE — read this before changing anything:
- Do NOT download or use the actual trending songs from TikTok/YouTube.
  They are almost always copyrighted, and using them draws Content ID
  claims, takedowns, and channel strikes. The match here is
  style/tempo/mood-ALIKENESS using a royalty-free track only.
- Every track in `music_library` must be royalty-free (Mixkit/Pixabay
  free tracks, or your own recordings) or a track you hold a licence
  for. If you do hold a licence for a specific track, put it in
  `licensed_track` with a `license_note` — that track is used as-is
  and the licence note is logged, but it is never presented as
  royalty-free.
- If a real (non-example) library is configured but no track matches
  the wanted genre/tempo/mood, this FAILS with a clear message naming
  the wanted profile, rather than silently using an unrelated track.
  A silent wrong track is worse than no track: it breaks the video's
  feel and can still be a rights problem if the fallback is unlicensed.
- If no library is configured at all (only EXAMPLE placeholder entries),
  narration ships without a music bed and a warning is printed — the
  same safe behaviour as before.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request

try:
    from src.config import load_config
except ImportError:
    from config import load_config


def load_profile(args, config):
    """Trending audio profile from --profile, --top5, or {} (unknown)."""
    if args.profile:
        if os.path.exists(args.profile):
            with open(args.profile, encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("trending_audio_profile", data)
        return json.loads(args.profile)
    if args.top5 and os.path.exists(args.top5):
        with open(args.top5, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("trending_audio_profile", {}) or {}
    return {}


def score_track(track, profile):
    """Score a library track against the trending profile.

    Genre match = 3, mood match = 2, tempo closeness = up to 2
    (full marks within 5 BPM, fading to 0 at 45 BPM away).
    A track only *qualifies* if it matches genre or mood, or if the
    profile is empty (no audio signal reported at all).
    """
    wanted_genre = (profile.get("genre") or "").lower()
    wanted_mood = (profile.get("mood") or "").lower()
    wanted_tempo = profile.get("tempo_bpm_median")
    genre = (track.get("genre") or "").lower()
    mood = (track.get("mood") or "").lower()
    score = 0.0
    reasons = []
    genre_match = bool(wanted_genre and genre == wanted_genre)
    mood_match = bool(wanted_mood and mood == wanted_mood)
    if genre_match:
        score += 3
        reasons.append(f"genre {genre} matches trending {wanted_genre}")
    if mood_match:
        score += 2
        reasons.append(f"mood {mood} matches trending {wanted_mood}")
    tempo = track.get("tempo_bpm")
    if isinstance(wanted_tempo, (int, float)) and isinstance(tempo, (int, float)):
        diff = abs(tempo - wanted_tempo)
        tempo_score = max(0.0, 2.0 - max(0.0, diff - 5) / 20.0)
        score += tempo_score
        reasons.append(f"tempo {tempo} BPM vs trending median {wanted_tempo} BPM (diff {diff:.0f})")
    qualifies = (not wanted_genre and not wanted_mood) or genre_match or mood_match
    return score, qualifies, reasons


def available_library(config):
    """Library tracks that are real and reachable; EXAMPLE placeholders skipped.

    Entries marked example: true, or with neither an existing local file
    nor an http(s) URL, are placeholders, not usable tracks.
    """
    out = []
    for track in config.get("music_library") or []:
        if not isinstance(track, dict):
            continue
        if track.get("example"):
            continue
        path = track.get("file") or track.get("url") or ""
        if path.startswith("http"):
            out.append(track)
        elif path and os.path.exists(path):
            out.append(track)
        else:
            print(f"WARNING: Skipping music library entry with missing file: {path}",
                  file=sys.stderr)
    return out


def select_track(config, profile):
    """Return (track_or_None, log_dict). Raises nothing; caller decides."""
    library = available_library(config)
    if not library:
        return None, {"reason": "no usable (non-example) music library configured"}
    scored = []
    for track in library:
        score, qualifies, reasons = score_track(track, profile)
        if qualifies:
            scored.append((score, track, reasons))
    if not scored:
        return None, {
            "reason": "no_match",
            "wanted": profile,
            "library_tried": [
                {"genre": t.get("genre"), "tempo_bpm": t.get("tempo_bpm"),
                 "mood": t.get("mood")} for t in library],
        }
    scored.sort(key=lambda item: item[0], reverse=True)
    score, track, reasons = scored[0]
    return track, {"score": round(score, 2), "reasons": reasons,
                   "track": {k: track.get(k) for k in ("file", "url", "genre", "tempo_bpm", "mood", "license")}}


def ensure_track_file(track):
    path = track.get("file") or track.get("url") or ""
    if path.startswith("http"):
        dest = os.path.join("data", "music_bed.mp3")
        os.makedirs("data", exist_ok=True)
        urllib.request.urlretrieve(path, dest)
        return dest
    return path


def legacy_music_file(config, music_arg):
    """Old single-file config (music_file / music_urls), kept as fallback
    only when no music_library is configured."""
    if music_arg and os.path.exists(music_arg):
        return music_arg
    if music_arg and music_arg.startswith("http"):
        dest = os.path.join("data", "music_bed.mp3")
        os.makedirs("data", exist_ok=True)
        urllib.request.urlretrieve(music_arg, dest)
        return dest
    local = config.get("music_file", "")
    if local and os.path.exists(local):
        return local
    for url in config.get("music_urls", []):
        if url.startswith("http"):
            dest = os.path.join("data", "music_bed.mp3")
            os.makedirs("data", exist_ok=True)
            urllib.request.urlretrieve(url, dest)
            return dest
    return ""


def mix_command(narration, music_path, output, music_volume):
    """ffmpeg argv mixing a music bed under narration.

    Level fix (production-readiness issue 4): ffmpeg's ``amix``
    defaults to ``normalize=1``, which divides the summed signal by
    the number of inputs — halving BOTH inputs (~6 dB quieter mix).
    ``normalize=0`` keeps each input at its own level, so the
    narration stays at full level and the bed stays at exactly the
    configured relative volume (e.g. 0.06) in narration-silent gaps.

    Looping fix (same issue): the bed is looped indefinitely
    (``-stream_loop -1`` on the music input) and ``amix`` is told
    ``duration=first``, so a bed shorter than the narration (the
    in-house bed is 64s) repeats to cover the whole narration
    instead of cutting out mid-video. The mix still ends exactly
    at the narration's end; nothing after it is kept.
    """
    filt = (
        f"[1:a]volume={music_volume}[music];"
        "[0:a][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0"
    )
    return ["ffmpeg", "-y", "-i", narration, "-stream_loop", "-1",
            "-i", music_path, "-filter_complex", filt,
            "-c:a", "libmp3lame", output]


# --- Loudness master (-14 LUFS / -1 dBTP) ---------------------------------
# Why this exists (2026-11-16): the finished v2 Short measured
# -26.35 LUFS / -9.62 dBTP — about 12 LUFS below the channel target —
# because the mix used plain amix with no normalization and the video
# mux used bare `-c:a aac`. QA only checked mean/max volume, never
# integrated loudness or true peak on the finished file, so the quiet
# video passed 21/21.
#
# Why gain + limiter, not loudnorm's linear mode: this material has a
# ~17 dB crest factor (integrated -26.35 LUFS vs true peak -9.62
# dBTP). loudnorm linear mode can only apply one constant gain, so it
# must choose between the LUFS target and the TP cap — it cannot hit
# both. A loudnorm-measured gain to the LUFS target plus a lookahead
# limiter on the transient peaks can: the limiter shaves only the
# peaks, leaving the integrated loudness on target.
#
# AAC overshoot: the editing-engine previews measured -1.38 dBTP on
# the mix but +2.85 dBTP on the muxed MP4, so the limiter is capped
# 2 dB below the target (mix TP -3 dBTP) AND the muxed file itself is
# re-measured — the loop below lowers the limiter further if the
# encoded output still overshoots. The gate in src/qa.py measures the
# finished MP4 the same way, so a file that passes here passes there.
# Self-contained in the production path: no dependency on the
# uncommitted src/sound_design.py engine work.

TARGET_LUFS = -14.0
TARGET_TP_DB = -1.0
LUFS_TOLERANCE = 1.0
# Pre-encode true-peak headroom: the limiter caps sample peaks this
# far below the target TP, absorbing AAC encoding overshoot.
MIX_TP_HEADROOM_DB = 2.0
_LIMITER_ATTACK_MS = 5
_LIMITER_RELEASE_MS = 50
# Accept a normalized file when it sits inside the QA gate with
# margin (gate allows LUFS +/-1.0 and TP <= -1.0).
_ACCEPT_LUFS_MARGIN = 0.5
_ACCEPT_TP_MARGIN = 0.2


def measure_loudness(path):
    """EBU R128 measurement of a finished file via ffmpeg loudnorm.

    Returns {"input_i", "input_tp", "input_lra", "input_thresh"} as
    floats (integrated LUFS, true peak dBTP, loudness range, gating
    threshold). Raises RuntimeError if ffmpeg cannot measure the file
    — a measurement failure must never read as "quiet" or "loud".
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    result = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path, "-af",
         "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=300)
    text = result.stderr or ""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError(f"loudnorm produced no JSON for {path}")
    data = json.loads(text[start:end + 1])
    return {"input_i": float(data["input_i"]),
            "input_tp": float(data["input_tp"]),
            "input_lra": float(data["input_lra"]),
            "input_thresh": float(data["input_thresh"])}


def loudness_ok(measured, target_lufs=TARGET_LUFS, target_tp_db=TARGET_TP_DB,
                tolerance=LUFS_TOLERANCE):
    """True only if integrated loudness is on target (within tolerance)
    and true peak is at or under the cap. Returns (ok, detail)."""
    lufs = measured["input_i"]
    tp = measured["input_tp"]
    ok = abs(lufs - target_lufs) <= tolerance and tp <= target_tp_db
    detail = (f"integrated {lufs:.2f} LUFS "
              f"(target {target_lufs:.0f} +/-{tolerance:.0f}), "
              f"true peak {tp:.2f} dBTP (max {target_tp_db:.0f})")
    return ok, detail


def _has_video_stream(path):
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", path],
        capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe could not read {path}")
    info = json.loads(result.stdout or "{}")
    return any(s.get("codec_type") == "video"
               for s in info.get("streams", []))


def normalize_loudness(input_path, output_path, target_lufs=TARGET_LUFS,
                       target_tp_db=TARGET_TP_DB,
                       headroom_db=MIX_TP_HEADROOM_DB, max_attempts=3):
    """Normalize finished audio to the channel loudness master.

    Two-stage, self-verifying: (1) a loudnorm-measured gain lifts the
    mix to the LUFS target; (2) a lookahead limiter caps sample peaks
    at (target TP - headroom) dBFS so AAC encoding overshoot cannot
    push the muxed true peak over the cap. The ENCODED output file is
    re-measured each attempt; if it is still out of spec the gain is
    corrected by the LUFS shortfall and/or the limiter is lowered, and
    the pass repeats from the original input.

    For an MP4 input the video stream is copied untouched — only the
    audio is re-encoded (AAC 192k, faststart). For an audio-only input
    the output codec follows the output extension (.mp3/.wav, else
    AAC). Raises RuntimeError if it cannot converge within
    max_attempts. Returns a report dict with the input/output
    measurements and every attempt.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required for loudness normalization")
    measured_in = measure_loudness(input_path)
    has_video = _has_video_stream(input_path)
    gain_correction = 0.0
    limiter_db = target_tp_db - headroom_db
    attempts = []
    for attempt in range(1, max_attempts + 1):
        gain_db = target_lufs - measured_in["input_i"] + gain_correction
        limit_linear = 10 ** (limiter_db / 20.0)
        filt = (f"volume={gain_db:.2f}dB,"
                f"alimiter=limit={limit_linear:.4f}:level=false:"
                f"attack={_LIMITER_ATTACK_MS}:release={_LIMITER_RELEASE_MS}")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", input_path,
               "-af", filt]
        if has_video:
            cmd += ["-map", "0:v", "-c:v", "copy", "-map", "0:a",
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart"]
        elif output_path.lower().endswith(".mp3"):
            cmd += ["-c:a", "libmp3lame", "-b:a", "192k"]
        elif output_path.lower().endswith(".wav"):
            cmd += ["-c:a", "pcm_s16le"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd.append(output_path)
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=600)
        if result.returncode != 0:
            raise RuntimeError(
                "loudness normalize pass failed: "
                f"{(result.stderr or '')[-500:]}")
        measured_out = measure_loudness(output_path)
        attempts.append({"attempt": attempt,
                         "gain_db": round(gain_db, 2),
                         "limiter_db": round(limiter_db, 2),
                         "input_i": measured_out["input_i"],
                         "input_tp": measured_out["input_tp"]})
        lufs_ok = abs(measured_out["input_i"] - target_lufs) <= _ACCEPT_LUFS_MARGIN
        tp_ok = measured_out["input_tp"] <= target_tp_db - _ACCEPT_TP_MARGIN
        if lufs_ok and tp_ok:
            return {"input": input_path, "output": output_path,
                    "input_measured": measured_in,
                    "output_measured": measured_out,
                    "attempts": attempts,
                    "target_lufs": target_lufs,
                    "target_tp_db": target_tp_db}
        # Next attempt: lift the gain by the LUFS shortfall (the
        # limiter eats part of it) and lower the limiter if the muxed
        # true peak still overshoots the cap.
        gain_correction += target_lufs - measured_out["input_i"]
        if measured_out["input_tp"] > target_tp_db - _ACCEPT_TP_MARGIN:
            limiter_db -= (measured_out["input_tp"]
                           - (target_tp_db - _ACCEPT_TP_MARGIN)) + 0.5
    raise RuntimeError(
        "loudness normalization did not converge in "
        f"{max_attempts} attempts (last: {attempts[-1]}); "
        f"input measured {measured_in}")


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
    except Exception as exc:  # logging must never break the mix itself
        print(f"WARNING: could not append to run log ({exc})", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--narration", required=True)
    parser.add_argument("--music", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--music-volume", type=float, default=0.15)
    parser.add_argument("--top5", default="data/top5.json")
    parser.add_argument("--profile", default="")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    profile = load_profile(args, config)
    # Weekly-review override (safe bound): if the last review found a
    # winning music profile, it overrides the trending profile for the
    # match, and the override is logged below.
    review_profile = {}
    if config.get("review_music_genre"):
        review_profile["genre"] = config["review_music_genre"]
    if config.get("review_music_tempo_bpm"):
        review_profile["tempo_bpm_median"] = config["review_music_tempo_bpm"]
    if config.get("review_music_mood"):
        review_profile["mood"] = config["review_music_mood"]
    if review_profile:
        profile = {**profile, **review_profile,
                   "review_override": review_profile}
        print(f"Music profile overridden by weekly review: {review_profile}")
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    # Licensed track (user holds a licence) wins outright, with its note logged.
    licensed = config.get("licensed_track", "")
    if licensed and os.path.exists(licensed):
        music = licensed
        match_log = {"licensed_track": licensed,
                     "license_note": config.get("license_note", ""),
                     "note": "Licensed track used as-is; NOT claimed royalty-free."}
        print(f"Licensed track: {licensed} ({config.get('license_note', '')})")
    elif args.music:
        music = legacy_music_file(config, args.music)
        match_log = {"explicit_music_arg": args.music}
    else:
        track, match_log = select_track(config, profile)
        if track is None and match_log.get("reason") == "no_match":
            wanted = match_log.get("wanted", {})
            print(
                "ERROR: No royalty-free track in music_library matches the "
                f"trending audio profile (genre={wanted.get('genre') or 'unknown'}, "
                f"tempo={wanted.get('tempo_bpm_median') or 'unknown'} BPM, "
                f"mood={wanted.get('mood') or 'unknown'}). "
                "Add a matching royalty-free track to music_library in "
                "config.yaml instead of using an unrelated track — and "
                "never substitute the actual trending copyrighted song.",
                file=sys.stderr,
            )
            return 1
        if track is None:
            music = legacy_music_file(config, "")
            match_log = {"reason": "no usable library; legacy fallback used"}
        else:
            music = ensure_track_file(track)
            match_log["trending_profile"] = profile
            print(f"Music match: trending profile {profile} -> "
                  f"{track.get('file') or track.get('url')} "
                  f"(score {match_log.get('score')}; {'; '.join(match_log.get('reasons', []))})")
    append_run_log("music", match_log)

    if not music:
        print(
            "WARNING: No royalty-free music file found — shipping narration "
            "without a music bed. Add a matching track to music_library in "
            "config.yaml to enable trending-style music.",
            file=sys.stderr,
        )
        shutil.copyfile(args.narration, args.output)
        return 0
    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg is required to mix music.", file=sys.stderr)
        return 1
    # Mix via mix_command: amix normalize=0 (no ~6 dB drop) with the
    # bed looped to cover narration longer than the bed.
    subprocess.run(
        mix_command(args.narration, music, args.output, args.music_volume),
        check=True,
    )
    print(f"Mixed -> {args.output} (music bed at volume {args.music_volume})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
