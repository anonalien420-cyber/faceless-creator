# Pipeline config record — Deep Scan Antikythera Short, 2026-11-15

## Branch / code
- Work tree: `~/workspace/faceless-creator-branch/`, branch
  `feature/deep-scan-evidence-engine`, stated head `44c0ab7e` (per the
  task brief; no `git` was run in this session, so the head was not
  re-verified by command).
- `config.yaml` used: copied verbatim to `config.yaml` in this production
  dir. Narration: `narrator_voice: bm_george`, `narrator_tier: local`,
  `narrator_speed: 0.9`, `narrator_pause_ms: 350`. Music library entry
  `music/mellow_history_bed.mp3` (ambient, 60 bpm, mellow, synthesized
  in-house, royalty-free). Visuals: `visual_source: stock_video`,
  `min_resolution: 1080`, `video_bitrate: 10M`. Upload mode: `draft`.
- Files changed by this run (unpushed):
  - `src/video.py` — xfade-overlap duration fix; ASS `[Events]` Format
    now lists all 10 fields; new `_fit_fontsize()` title fit.
  - `tests/test_video_xfade_duration.py` — new, 3 tests.
  - `tests/test_video_captions_title.py` — new, 4 tests.
  - `data/run_log.json` — appended by branch narrate.py/music.py
    (3 steps: narrate main, music, narrate subscribe).
  - `productions/antikythera-short-2026-11-15/` — new, this production.
- Full suite after the fixes: 187/187 OK
  (`python3 -m unittest discover -s tests`, 2026-11-15 ~20:39 UTC).

## Evidence
- Ledger: `data/evidence_ledger.json`, sha256
  `b36aeadd8e6c9becbb3e8096f12e4585a143220adf9b712e763707ee5325aa87`
  (copy in this dir as `evidence_ledger.json`; excerpt + source list in
  `evidence-references.json`). 12 claims (10 KNOWN, 1 DEBATED, 1 UNKNOWN),
  6 sources APPROVED, reviewer Kristian, reviewed 2026-11-03/04/05,
  verification report PASS. Provenance: transcription of Kristian's human
  review of the published long-form (YouTube `k_wGkEfT5QI`, Public Nov 6).
- Package: 151 words, 7 claims (antikythera_01–05, 09, 10), hook
  antikythera_01, 7 scenes (`documentary_package.json`).

## Narration / music
- Narration: Kokoro `bm_george`, speed 0.9, `~/workspace/tts_venv/`,
  63.025s, 24 kHz mp3 (`narration-kokoro-bm_george-0.9.mp3`, mean −24.9 dB,
  max −7.6 dB). Subscribe line "Like and subscribe for more!": same
  voice/speed, 2.775s (`subscribe-narration-kokoro-bm_george-0.9.mp3`).
  Narration text in `narration.txt`; voice approval/listen-check by the
  user is still OPEN — these files are the listen material.
- Music bed: `music/mellow_history_bed.mp3`, 256,461 bytes, md5
  `a403f4c3abf28a886e89319c523515d9`, 64.0s, mixed at 0.06 via branch
  `src/music.py` (amix normalize=0, bed looped). Gap verification:
  25.6–26.2s mixed −45.4 dB vs bed alone −20.5 dB; 52.9–53.5s −42.9 dB
  vs −18.0 dB (24.9 dB attenuation; theoretical 0.06 = 24.4 dB).
- Close bed: v3/v4 recipe value 0.22 with bed window 6.0–10.6s +
  0.8s fade-out (see production-log §9 for why it differs from the
  0.06 body mix: the 0.06 bed sits below QA's −40 dB silence floor,
  and the v3 recipe's atrim dropped the bed entirely on ffmpeg 8.1
  until `asetpts=PTS-STARTPTS` was added).

## Render
- ffmpeg 8.1.2 (ffprobe 8.1.2).
- Body render command (final, fixed build):
  ```
  python3 -m src.video --input productions/antikythera-short-2026-11-15/scripts.json \
    --audio-dir productions/antikythera-short-2026-11-15 \
    --outdir productions/antikythera-short-2026-11-15/body --format short \
    --end-card-text "Like and subscribe for more!" \
    --visuals productions/antikythera-short-2026-11-15/visuals/gears_loop16.mp4 \
             productions/antikythera-short-2026-11-15/visuals/wreck_loop12.mp4 \
             productions/antikythera-short-2026-11-15/visuals/cogwheels.mp4 \
             productions/antikythera-short-2026-11-15/visuals/museum_loop12.mp4 \
             productions/antikythera-short-2026-11-15/visuals/pocketwatch.mp4 \
             productions/antikythera-short-2026-11-15/visuals/aegean.mp4
  ```
  Body: 63.000s, 1080×1920, 30fps, H.264 + AAC, 10M, 7 chunks of 9.43s
  (xfade 0.5s), eq contrast 1.05 / saturation 1.10, ASS captions (22
  chunks), title card + hook line (first 3–5s), progress bar, end card
  in last 3s of body.
- Subscribe close (v4 recipe, adapted — branch video.py has no
  subscribe-close mechanism): owl zoompan 138 frames + yellow drawtext
  "Like and subscribe for more!" (fontsize 60, #FFCC00, y=h−90);
  sub_audio = VO apad 4.6s + bed atrim=6:10.6, asetpts=PTS-STARTPTS,
  volume 0.22, afade out st=3.8 d=0.8, amix normalize=0; muxed
  `-c:v copy -c:a aac -b:a 192k -movflags +faststart`.
- Final: concat demuxer, stream copy, `-movflags +faststart`:
  body (63.000s) + subscribe (4.600s) = 67.643s.
- Visuals per chunk (branch pattern-interrupt cycle, ~9.43s each):
  0 gears_loop16 (hook, antikythera_01) · 1 wreck_loop12 (dive,
  antikythera_02) · 2 cogwheels (gear spotted, antikythera_03) ·
  3 museum_loop12 (fragments, antikythera_04) · 4 pocketwatch (built
  ~100 BCE, antikythera_05) · 5 aegean (1,400-year gap,
  antikythera_09) · 6 gears_loop16 (unknown builder, antikythera_10 +
  CTA). Gradient fallback: 0 scenes. All clips real Pexels stock
  (manifest: `~/workspace/faceless-creator/previews/stock/manifest.json`).

## QA / verification
- Branch QA: PASS 21/21, fixes none (`qa_report.json`).
- ffprobe final: 1080×1920, 30/1 fps, H.264 + AAC 24 kHz mono,
  67.643s, 79,243,966 bytes; moov before mdat (faststart).
- Full decode: clean. No black >2s; no silence >2s.
- Beep scan (`beep_scan.py` + `beep_scan.json`): 1 sustained event,
  53.0–53.375s, 440 Hz, −46.5 dB (bed note in a narration pause at
  0.06 mix); 0 events above −40 dB; close clean. See production-log §10.
- Frame checks (frames/): t=2, 15, 30, 45, 58, 64.5, 66.5 — all read
  visually; captions clean and in sync; outro owl + red SUBSCRIBE +
  yellow line at 64.5s and 66.5s; no globe; no line art.
- Thumbnail: branch `src/thumbnail.py`, 1080×1920, text "Ancient
  Machine Predicted Eclipses" (validated against the script), QA PASS
  (pixel stddev 70.7).

## Upload gates (verified live 2026-11-15 ~20:47 UTC, no upload performed)
- `--public` → exit 1: "ERROR: Public or scheduled publishing is
  disabled. Review and publish manually in YouTube Studio."
- Plain run (no env) → exit 1: "ERROR: Refusing upload:
  HUMAN_REVIEW_APPROVED must be set to true after reviewing the
  evidence ledger and review queue."
- `--dry-run` → exit 0: "DRY RUN — nothing uploaded",
  plan {privacyStatus: "unlisted", categoryId: "27"}.
- `--auto-public` → exit 1: same disabled-publishing error.
- HUMAN_REVIEW_APPROVED / UPLOAD_ENABLED were never set; no upload
  secret was created or used.

## Deliberately left out / open
- Duration: 67.6s total (63.0s narration + 4.6s close), over the ~60s
  target. The 151-word package at the locked 0.9 speed renders 63.0s;
  trimming words would break the evidence gate (QA rebuilds the script
  from the ledger byte-for-byte), and the speed is locked in config.
- Narration listen-check by the user: OPEN (narration + mix files are
  the listen material; voice NOT claimed approved).
- Title card reads "Shouldn'T" (branch `.title()` quirk) — left as is.
- No ComfyUI visuals (no host exists); no cartoon clips used.
- Not published, not uploaded (dry-run only, per task + gates).
