# Pipeline config record — Deep Scan Antikythera Short v2 (audio + subtitle refinement), 2026-11-16

## Branch / code
- Work tree: `~/workspace/faceless-creator-branch/`, branch
  `feature/deep-scan-evidence-engine`, head `4f72304b1` at start
  (thumbnail commit; no `git` was run in this session — the tree is
  not a git repository, so the head was verified via the connector
  before the task and re-checked at start).
- `config.yaml` used: copied verbatim to `config.yaml` in this
  production dir (same as v1). Narration: `narrator_voice: bm_george`,
  `narrator_tier: local`, `narrator_speed: 0.9`,
  `narrator_pause_ms: 350`. Music library entry
  `music/mellow_history_bed.mp3` (ambient, 60 bpm, mellow, synthesized
  in-house, royalty-free). Visuals: `visual_source: stock_video`,
  `min_resolution: 1080`, `video_bitrate: 10M`. Upload mode: `draft`.
- Files changed by this run (unpushed; v2 production):
  - NEW `data/pronunciation_dictionary.json` (14 entries) +
    `src/pronunciation.py` + `tests/test_pronunciation.py`.
  - `src/narrate.py` — pronunciation-dictionary wiring
    (`--pronunciation-dictionary`, applied in memory at narration
    time); `humanize_text` plain pauses extended to "? ", "! ", ": ";
    new `sentence_pauses()` (hook +0.3s, closing questions +0.2s);
    new `insert_silence()` (exact silence insertion at measured
    times); `narrate_kokoro` REVERTED to the single-call path (a
    per-sentence variant was tried and reverted — it made Kokoro speak
    ~20% slower, 80.4s vs 63.0s for the same 151 words).
  - `src/video.py` — new `align_script_to_timings()` (+
    `_canonical_tokens()`, `_number_value()`); `make_ass()` gains
    `word_timings=` (timed ≤3-word UPPERCASE captions) and
    `extra_captions=`; `build_video()` gains `word_timings=`; new
    `--word-timings` CLI option.
  - `tests/test_narration_audio.py` — SentencePausesTests,
    KokoroSingleCallTests, InsertSilenceTests, humanize ?/: test.
  - `tests/test_video_captions_timing.py` — new (alignment + timed ASS).
  - `data/run_log.json` — appended by branch narrate.py/music.py.
  - `productions/antikythera-short-2026-11-15-v2/` — new, this production.
- Full suite: see production-log §15 / the final report (one
  pre-existing failure in `tests/test_caption_presets.py`, unrelated
  to this task — `segment_words` in `src/caption_presets.py`, a module
  this task does not touch).

## Evidence (unchanged from v1 — no claim, tier, source, or review status changed)
- Ledger: `data/evidence_ledger.json`, md5
  `6f016dbb17b874400dacc153367048d6` (copy in this dir as
  `evidence_ledger.json`; excerpt + source list in
  `evidence-references.json`). 12 claims (10 KNOWN, 1 DEBATED,
  1 UNKNOWN), 6 sources APPROVED, reviewer Kristian, reviewed
  2026-11-03/04/05, verification report PASS. Provenance:
  transcription of Kristian's human review of the published long-form
  (YouTube `k_wGkEfT5QI`, Public Nov 6).
- Package: 151 words, 7 claims (antikythera_01–05, 09, 10), hook
  antikythera_01, 7 scenes (`documentary_package.json`, unchanged).
- Pronunciation fixes change NO words or meanings: the dictionary is
  applied only in memory at narration time (Kokoro respelling "Stais"
  → "Stah ees"); the ledger, script text, and subtitles keep the
  correct written forms.

## Narration / music
- Narration: Kokoro `bm_george`, speed 0.9, `~/workspace/tts_venv/`,
  raw 63.100s (v1: 63.025s; +0.075s from the two-syllable "Stah ees"),
  24 kHz mp3 (`narration-kokoro-bm_george-0.9.mp3`, 404,616 bytes).
  After pacing insertion: `audio/01-...-final.mp3`, 63.600s, 509,421
  bytes. Pacing beats (insert_silence, silence-anchored): hook +0.3s
  at 6.23s (gap 0.445s → 0.745s); closing questions +0.2s at 59.91s.
  Narration text in `narration.txt`; voice approval/listen-check by
  the user is still OPEN — these files are the listen material.
  Subscribe line "Like and subscribe for more!": REUSED from v1 (same
  voice/speed, 2.775s; VO re-transcribed, all 5 words correct).
- Music bed: `music/mellow_history_bed.mp3`, 256,461 bytes, md5
  `a403f4c3abf28a886e89319c523515d9`, 64.0s, mixed at 0.06 via branch
  `src/music.py`. Gap verification (volumedetect): hook gap 6.3–6.9s
  mixed −45.7 dB vs bed alone −21.2 dB (24.5 dB attenuation);
  53.4–53.9s mixed −44.0 dB vs bed alone −19.1 dB (24.9 dB);
  theoretical 0.06 = 24.4 dB. Mix is 63.600s, 254,829 bytes.
- Close bed: REUSED v1 close clip + sub_audio (v3/v4 recipe value
  0.22 with bed window 6.0–10.6s + 0.8s fade-out; see v1 config
  record for why it differs from the 0.06 body mix).

## Render
- ffmpeg 8.1.2 (ffprobe 8.1.2).
- Body render command:
  ```
  python3 -m src.video --input productions/antikythera-short-2026-11-15-v2/scripts.json \
    --audio-dir productions/antikythera-short-2026-11-15-v2 \
    --outdir productions/antikythera-short-2026-11-15-v2/body --format short \
    --end-card-text "Like and subscribe for more!" \
    --visuals productions/antikythera-short-2026-11-15-v2/visuals/gears_loop16.mp4 \
             productions/antikythera-short-2026-11-15-v2/visuals/wreck.mp4 \
             productions/antikythera-short-2026-11-15-v2/visuals/cogwheels.mp4 \
             productions/antikythera-short-2026-11-15-v2/visuals/museum_loop12.mp4 \
             productions/antikythera-short-2026-11-15-v2/visuals/pocketwatch.mp4 \
             productions/antikythera-short-2026-11-15-v2/visuals/aegean.mp4 \
    --word-timings productions/antikythera-short-2026-11-15-v2/word_timings_final.json
  ```
  Body: 63.566s, 1080×1920, 30fps, H.264 + AAC, 10M, 7 chunks
  (xfade 0.5s), eq contrast 1.05 / saturation 1.10, ASS captions (51
  timed lines, ≤3 words, UPPERCASE), title card + hook line (first
  3–5s), progress bar, end card in last 3s of body.
- Subscribe close: REUSED byte-identical from v1 (`subscribe.mp4`
  md5 36fd18c1870571bf80854add4d261944; `sub_audio.wav` md5
  2c47a0a7334b165b6ed2edbc7ca7ec35). Owl zoompan + yellow drawtext
  "Like and subscribe for more!" (fontsize 60, #FFCC00, y=h−90).
- Final: concat demuxer, stream copy, `-movflags +faststart`:
  body (63.566s) + subscribe (4.600s) = 68.209s.
- `final-audio.mp3`: mixed-audio + sub_audio via the CONCAT FILTER
  (the concat demuxer failed on mp3 with "Header missing" and
  produced a body-only file — same as v1), 68.200s.
- Visuals per chunk (same order as v1): 0 gears_loop16 (hook,
  antikythera_01) · 1 wreck (dive, antikythera_02) · 2 cogwheels (gear
  spotted, antikythera_03) · 3 museum_loop12 (fragments,
  antikythera_04) · 4 pocketwatch (built ~100 BCE, antikythera_05) ·
  5 aegean (1,400-year gap, antikythera_09) · 6 gears_loop16 (unknown
  builder, antikythera_10 + CTA). Gradient fallback: 0 scenes. All
  clips real Pexels stock.
- Sidecar ASS: body ASS (51 lines) + 2 VO-timed close lines, offset
  by the body duration 63.566s: "LIKE AND SUBSCRIBE" 63.57–64.79,
  "FOR MORE!" 64.79–65.51 (v1 used uniform splits of the 4.6s close).

## QA / verification
- Branch QA: PASS 21/21, fixes none (`qa_report.json`).
- ffprobe final: 1080×1920, 30/1 fps, H.264 + AAC 24 kHz mono,
  68.209s, 80,076,448 bytes, sha256
  8f235cf94dee3a8a4b01d24908a77df12e90e6122ad23fcb4a3db834bd629dfa;
  moov before mdat (faststart).
- Full decode: clean. No black >2s; no silence >2s.
- Beep scan (`beep_scan.py` + `beep_scan.json`): 1 sustained event,
  53.125–53.75s, 440 Hz, −46.7 dB (same bed note as v1, shifted +0.3s
  by the hook beat); 0 events above −40 dB; close clean. See
  production-log §11.
- Frame checks (frames/): t=2, 15, 30, 45, 58, 64.5, 66.5 — all read
  visually; captions clean, uppercase, in sync; outro owl + red
  SUBSCRIBE + yellow line at 64.5s and 66.5s; no globe; no line art.
- Thumbnail: branch `src/thumbnail.py`, 1080×1920, text "Ancient
  Machine Predicted Eclipses" (validated against the script), QA PASS
  (pixel stddev 70.6; v1: 70.7).

## Upload gates
Not re-run for v2 (no code change to src/upload.py or the gates;
v1's gate checks stand). No upload performed; no gate env vars set.

## Deliberately left out / open
- Duration: 68.2s total (63.6s narration + 4.6s close), over the ~60s
  target — same as v1 (67.6s) plus the 0.5s of pacing beats. The
  151-word package at the locked 0.9 speed renders 63.1s; trimming
  words would break the evidence gate, and the speed is locked.
- Narration listen-check by the user: OPEN (narration + mix files are
  the listen material; voice NOT claimed approved).
- Title card reads "Shouldn'T" (branch `.title()` quirk) — left as is
  (visual, approved).
- "Stais" is rendered as "Stah ees" (two syllables, final consonant
  voiced /z/ rather than Greek /s/ — the /s/ variant "Stah eess" was
  tested and heard as "Star East", worse). "Valerios" is rendered as
  written (heard as "Valerio's" — acceptable, no respelling applied
  because none is verified).
- UNKNOWN pronunciations (no respelling applied): Exeligmos,
  Taposiris Magna, ScanPyramids (dictionary entries flagged UNKNOWN).
- No ComfyUI visuals (no host exists); no cartoon clips used.
- Not published, not uploaded (dry-run only, per task + gates).
