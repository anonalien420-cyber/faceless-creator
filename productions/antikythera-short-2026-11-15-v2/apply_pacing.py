"""Apply pacing beats to the v2 Antikythera narration (production step).

Steps:
  1. Transcribe the raw single-call narration (faster-whisper small,
     word timestamps) and verify it against the script.
  2. Find the two beat boundaries from the script's sentence structure
     (sentence_pauses: after the hook, +0.3s; between the two closing
     questions, +0.2s) and take their end times from the aligned word
     timings.
  3. Insert the silence with src.narrate.insert_silence() -> final
     narration mp3.
  4. Shift the word timings analytically by the inserted amounts and
     save the final timings JSON for the video CLI (--word-timings).

Usage (from the branch root):
  python3 productions/antikythera-short-2026-11-15-v2/apply_pacing.py
"""
import json
import os
import re
import subprocess
import sys

import numpy as np
from faster_whisper import WhisperModel

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from src.narrate import insert_silence, sentence_pauses  # noqa: E402
from src.video import align_script_to_timings  # noqa: E402

PROD = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(PROD, "audio", "01-the-2-000-year-old-object-that-shouldn-t-exist.mp3")
FINAL = os.path.join(PROD, "audio", "01-the-2-000-year-old-object-that-shouldn-t-exist-final.mp3")
TIMINGS = os.path.join(PROD, "word_timings_final.json")
SCRIPT_TXT = os.path.join(PROD, "narration.txt")


def decode_16k_mono(path):
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000",
         "-f", "f32le", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def transcribe(path, model):
    audio = decode_16k_mono(path)
    segments, _ = model.transcribe(audio, language="en", beam_size=5,
                                   word_timestamps=True)
    words = []
    for seg in segments:
        for w in seg.words:
            words.append((round(w.start, 3), round(w.end, 3), w.word.strip()))
    return words


def find_silences(path):
    """Return [(start, end)] of silences in `path` (ffmpeg
    silencedetect, -40 dB, >=0.1s). Used to anchor pacing insertions
    in the real audio gap, not in Whisper's estimated word end."""
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path,
         "-af", "silencedetect=noise=-40dB:d=0.1", "-f", "null", "-"],
        capture_output=True, text=True, check=True).stderr
    silences = []
    pending_start = None
    for line in out.splitlines():
        m = re.search(r"silence_start: ([\d.]+)", line)
        if m:
            pending_start = float(m.group(1))
        m = re.search(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)",
                      line)
        if m and pending_start is not None:
            silences.append((pending_start, float(m.group(1))))
            pending_start = None
    return silences


def anchor_insertion(word_end, silences):
    """Best insertion point for a beat after a word ending at `word_end`:
    the start of the first real silence beginning within 0.5s after the
    word end. Whisper's word-end times run ~0.05-0.1s early (the vowel
    tail is still audible), so inserting exactly at the word end can
    split the word's tail; anchoring in the silence avoids that."""
    for start, _end in silences:
        if word_end - 0.1 <= start <= word_end + 0.5:
            return start
    return word_end + 0.05


def main():
    with open(SCRIPT_TXT, encoding="utf-8") as fh:
        script = fh.read().strip()
    model = WhisperModel("small", device="cpu", compute_type="int8")
    timed = transcribe(RAW, model)
    print(f"Raw narration: {len(timed)} words, "
          f"{timed[-1][1]:.2f}s, heard: {' '.join(w for _, _, w in timed)[:120]}...")
    # Align script words to the transcription; the aligned spans give
    # the end time of each script word (correct written forms).
    aligned = align_script_to_timings(script.split(), timed)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", script.strip()) if s]
    pauses_idx = sentence_pauses(script)
    print(f"Beats (sentence_pauses): {pauses_idx}")
    # Boundary word index for each beat: the last word of that sentence.
    # The insertion point is anchored in the real silence after the
    # word (see anchor_insertion), not in Whisper's word-end estimate.
    silences = find_silences(RAW)
    inserts = []
    word_idx = 0
    for i, sent in enumerate(sentences):
        n_words = len(sent.split())
        if i in pauses_idx:
            # End time of this sentence's last word.
            word_end = aligned[word_idx + n_words - 1][1]
            at = anchor_insertion(word_end, silences)
            inserts.append((at, pauses_idx[i]))
            print(f"  beat after sentence {i + 1} ({sent[:40]!r}...): "
                  f"word ends {word_end:.2f}s, insert +{pauses_idx[i]}s "
                  f"at {at:.2f}s (silence-anchored)")
        word_idx += n_words
    if not inserts:
        print("No beats to apply; copying raw narration as final.")
        subprocess.run(["cp", RAW, FINAL], check=True)
        shifted = [[s, e, w] for s, e, w in timed]
    else:
        new_dur = insert_silence(RAW, FINAL, inserts)
        print(f"Final narration: {new_dur:.3f}s")
        # Shift timings analytically: a word moves later by the sum of
        # all insertions at or before its start/end.
        shifted = []
        for s, e, w in timed:
            ds = sum(d for t, d in inserts if t <= s)
            de = sum(d for t, d in inserts if t <= e)
            shifted.append([round(s + ds, 3), round(e + de, 3), w])
    with open(TIMINGS, "w", encoding="utf-8") as fh:
        json.dump(shifted, fh)
    print(f"Saved {len(shifted)} shifted word timings to {TIMINGS}")
    # Verify the Stais phrase in the raw transcription.
    for s, e, w in timed:
        if w.lower().rstrip(".,") in ("stais", "stah", "ees", "star", "ease"):
            print(f"  STAIS-REGION raw: {s:.2f}-{e:.2f} {w!r}")


if __name__ == "__main__":
    main()
