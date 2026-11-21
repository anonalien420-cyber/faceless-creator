# Production log — Deep Scan Antikythera Short v2, loudness fix (2026-11-16)

All times UTC. Work tree: `~/workspace/faceless-creator-branch/` (branch
`feature/deep-scan-evidence-engine`, head `89238ef83` at start — the v2
audio + subtitle refinement, already committed). No push of this fix yet,
no `.github/workflows/` touch, no `git` run, no upload, no workflow
trigger. No secrets used, copied, or set.

## 0. The finding (verified, not assumed)

The delivered v2 MP4 measures **−26.35 LUFS / −9.62 dBTP** (ffmpeg 8.1.2
loudnorm) — about 12 LUFS below the channel target of −14 LUFS / −1
dBTP. It would play noticeably quiet on phone speakers. The v1 MP4
measures −25.89 LUFS / −8.34 dBTP — the same systemic problem, not a
v2 regression. Root cause: production uses `src/music.py` mix_command
(plain amix, no normalization) and `src/video.py` muxes with bare
`-c:a aac`; `src/qa.py` checked only audio_present / audio_not_silent /
audio_not_clipping — never integrated loudness or true peak on the
finished file. The v2 QA report records mean −25.9 dB and still passed
21/21. The loudnorm master in `src/sound_design.py` (TARGET_LUFS −14.0,
TARGET_TP_DB −1.0) exists but production never calls it — and that file
is uncommitted editing-engine work, so the production path does NOT
depend on it; the fix below is self-contained in the production path.

Chain measurements (loudnorm, all pre-fix):
- Kokoro narration (raw): −25.27 LUFS / −9.17 dBTP
- Mixed audio (narration + bed at 0.06): −26.16 LUFS / −10.00 dBTP
- Subscribe close audio: −27.78 LUFS / −9.59 dBTP
- v2 MP4 (muxed): −26.35 LUFS / −9.62 dBTP

## 1. Why gain + limiter, not loudnorm linear mode

This material has a ~17 dB crest factor (integrated −26.35 LUFS vs true
peak −9.62 dBTP). loudnorm's linear two-pass mode can only apply one
constant gain, so it must choose between the LUFS target and the TP
cap — it cannot hit both (verified in prototype: dynamic loudnorm at
TP −3 landed at −15.41 LUFS, outside the ±1 window). The fix is a
loudnorm-measured gain to the LUFS target plus a lookahead limiter on
the transient peaks: the limiter shaves only the peaks, leaving the
integrated loudness on target.

AAC overshoot: the editing-engine previews measured −1.38 dBTP on the
mix but +2.85 dBTP on the muxed MP4, so the limiter is capped 2 dB
below the target (mix TP −3 dBTP) AND the muxed file itself is
re-measured — the loop lowers the limiter further if the encoded
output still overshoots. Prototype on the real v2 file: attempt 1
(gain +12.35 dB, limiter −3 dB) → −14.77 LUFS / −2.21 dBTP; attempt 2
(gain +13.12 dB, same limiter) → −14.29 LUFS / −2.26 dBTP. Accepted
with margin inside the QA gate (±0.5 LUFS, TP ≤ −1.2 in the code).

## 2. Code changes (production path only)

- `src/music.py` (new loudness section, `mix_command` untouched):
  `TARGET_LUFS = -14.0`, `TARGET_TP_DB = -1.0`, `LUFS_TOLERANCE = 1.0`,
  `MIX_TP_HEADROOM_DB = 2.0`; `measure_loudness(path)` (EBU R128 via
  ffmpeg loudnorm, raises on measurement failure); `loudness_ok()`;
  `normalize_loudness(input, output, ...)` — loudnorm-measured gain +
  lookahead limiter (`alimiter`, attack 5 ms, release 50 ms), MP4
  inputs get video-copy + AAC 192k + faststart, audio-only inputs
  follow the output extension; re-measures the ENCODED output each
  attempt (max 3), corrects the gain by the LUFS shortfall and lowers
  the limiter on TP overshoot, raises if it cannot converge. Returns
  a report dict with input/output measurements and every attempt.
- `src/video.py`: `build_video(..., normalize_loudness=True)` — after a
  successful render (both fallback and visuals paths) the finished
  MP4 is loudness-normalized in place. Fail-soft: a normalization
  failure only warns and the un-normalized render is kept; the QA
  loudness gate is the fail-loud layer. Pass `False` only for tests
  that need the raw render.
- `src/qa.py`: new `audio_loudness` check in `check()` — measures the
  FINISHED MP4 with loudnorm, passes only on integrated −14 ±1 LUFS
  and true peak ≤ −1 dBTP; a measurement failure FAILS the check
  (never passes silently). `fix_and_recheck()` now tries the proper
  loudness normalization first when any audio-level check fails, with
  the legacy crude gain/cut as fallback. No existing check weakened.
- `tests/test_loudness.py` (new, 12 tests): loudnorm measurement
  parsing + `loudness_ok` boundaries (including the v2 measurement
  failing); normalize on a quiet MP4 (hits target, video stream
  byte-identical, duration preserved); normalize on a high-crest-factor
  fixture (sparse 15 ms transients over a quiet tone — the limiter
  must hold the MUXED true peak ≤ −1 while LUFS reaches target);
  audio-only MP3 branch; missing-file error; QA gate fails a quiet
  file / passes a normalized one; `run_qa` auto-fix normalizes a quiet
  file; `build_video` normalizes by default / keeps the raw render
  with `normalize_loudness=False`.
- Full suite: **452/452 OK** (440 baseline + 12 new) under
  `~/workspace/tts_venv/bin/python`, 87.9s.

Not touched: the uncommitted editing-engine / caption-preset files
(`src/editing_*.py`, `src/transitions.py`, `src/motion.py`,
`src/sound_design.py`, `src/caption_presets.py`,
`src/caption_treatments.py`, `src/hook.py`, `src/retention.py`,
`src/thumbnail_v2.py`, `assets/fonts/`,
`productions/editing-engine-previews/`,
`productions/caption-preset-previews/`), the v1 production dir, and
`src/narrate.py` / `src/run.py` (no change needed — run.py calls
video.py and qa.py, so the fix flows through the daily pipeline).

## 3. Corrected render (audio ONLY — same script, narration, visuals)

Produced by the new production code (`src.music.normalize_loudness`)
on the delivered v2 MP4 — audio-only remux, video stream copied:
```
DeepScan-Antikythera-Short-2026-11-15-v2-loudness-fix.mp4
```
- 80,395,013 bytes; 1080×1920, 30fps; video 68.166s, audio 68.217s
  (v2: 68.166s / 68.209s — the 8 ms audio difference is AAC encoder
  delay, inside QA's 2.0s tolerance).
- sha256
  d3505c711cad984c54db29099b660dd3b719f05688239b7a1e07316edc4823d7
  (v2: 8f235cf94dee3a8a4b01d24908a77df12e90e6122ad23fcb4a3db834bd629dfa)
- Measured on the MUXED file (loudnorm): **−14.29 LUFS / −2.26 dBTP**
  (input was −26.35 / −9.62). Normalization report: attempt 1 gain
  +12.35 dB → −14.77 / −2.21; attempt 2 gain +13.12 dB → −14.29 /
  −2.26 (accepted). LRA 2.2 → 2.1.
- Video-stream identity: raw H.264 bitstream sha256
  030f79e36f89738d9b4ff47a241088dd7caf5f57f33b69165e5a3cadafd84071 for
  BOTH files; 2045 frames each. Only the audio changed.
- Thumbnail: byte-identical copy of the v2 thumbnail (same visuals).
  ASS: byte-identical copy of the v2 sidecar (same subtitles, same
  timings — loudness normalization does not move audio in time).
  `final-audio.mp3` re-extracted from the corrected MP4 (68.224s).

## 4. QA (new gate included — 22 checks, was 21)

```
python3 -m src.qa --video <corrected> --narration <corrected>/final-audio.mp3 \
  --script-text "<narration.txt>" \
  --title "The 2,000-Year-Old Object That Shouldn't Exist" --format short \
  --script-json <corrected>/documentary_package.json --report <corrected>/qa_report.json
```
Result: **QA PASS, 22/22 checks, fixes: none.** The new check:
`audio_loudness pass — integrated -14.29 LUFS (target -14 +/-1),
true peak -2.26 dBTP (max -1)`. The other audio checks also improved:
mean −13.8 dB (v2: −25.9 dB), max −2.9 dB (v2: −9.7 dB). All 10
accuracy checks pass unchanged (same script, same ledger).

## 5. Beep scan (diagnostic, not a QA gate)

`beep_scan.py` (copied from v2) on the corrected final-audio:
2 sustained pure-tone events (v2: 1) — result "FAIL", the same verdict
v2's scan gave. The scan's thresholds are absolute, so the +13 dB
overall gain lifts existing mix content above them; NO new sounds
were introduced and the mix balance is unchanged (single-bus gain):
- 53.125–53.75s, 440.0 Hz, **−33.5 dB** (v2: −46.7 dB) — the KNOWN
  bed pad note, same relative level, now above the scan's −40 dB
  floor. Whether it is now audible enough to matter is a listen-check
  question, not a rebuild cause on its own.
- 22.5–22.75s, 524.0 Hz, **−36.6 dB** (new above threshold) — the bed
  at that time has no 524 Hz component (checked: peak 349 Hz, 4% of
  band energy), so this is a narration vowel harmonic in the "lump,
  and the museum's" region, lifted above the scan's −50 dBFS window
  threshold by the gain. Not a bed beep, not a new sound.

## 6. Deliveries copied to ~/workspace/your_files/
DeepScan-Antikythera-Short-2026-11-15-v2-loudness-fix.mp4,
DeepScan-Antikythera-Short-2026-11-15-v2-loudness-fix-thumb.png,
DeepScan-Antikythera-Short-2026-11-15-v2-loudness-fix-QA.json.

## 7. Commit (for the PR branch)
- `src/music.py`, `src/video.py`, `src/qa.py`, `tests/test_loudness.py`
- Production text evidence in this dir (production log, QA report,
  pipeline config record, beep scan + script, ASS, narration text,
  word timings, documentary package, evidence ledger + references,
  metadata, scripts.json).
- MP4 stays OUT of the repo by design (same as v1/v2).
