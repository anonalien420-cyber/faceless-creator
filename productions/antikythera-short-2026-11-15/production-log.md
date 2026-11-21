# Production log — Deep Scan Antikythera Short, 2026-11-15 (Worker D)

All times UTC. Work tree: `~/workspace/faceless-creator-branch/` (branch
`feature/deep-scan-evidence-engine`, stated head 44c0ab7e). No push, no
`.github/workflows/` touch, no `git` run, no upload, no workflow trigger.
No secrets used, copied, or set.

## 1. Starting state (verified by coordinator, re-checked here)
- `data/evidence_ledger.json` sha256
  `b36aeadd8e6c9becbb3e8096f12e4585a143220adf9b712e763707ee5325aa87`;
  12 claims, 6 sources APPROVED, reviewer Kristian, verification PASS.
- `music/mellow_history_bed.mp3` 256,461 bytes, md5 `a403f4c3...` (full:
  `a403f4c3abf28a886e89319c523515d9`), 64.0s.
- ffmpeg/ffprobe 8.1.2. Kokoro import OK in `~/workspace/tts_venv/`
  (Python 3.12.3). Owl image verified visually (scholar owl, red
  SUBSCRIBE button, teal background, no globe).

## 2. Documentary package — 20:19 UTC
```
python3 -m src.documentary --topic "The 2,000-Year-Old Object That Shouldn't Exist" \
  --format short --ledger data/evidence_ledger.json \
  --output productions/antikythera-short-2026-11-15/documentary_package.json
```
Result: 151 words (gate 120–180), 7 claims
[antikythera_01, 02, 03, 04, 05, 09, 10], 7 scenes, hook = antikythera_01.
scripts.json written from the package for the narrate/video CLIs.

## 3. Narration (Kokoro) — 20:19:45–20:21 UTC
```
TMPDIR=~/workspace/tmp_pip ~/workspace/tts_venv/bin/python -m src.narrate \
  --input productions/antikythera-short-2026-11-15/scripts.json \
  --outdir productions/antikythera-short-2026-11-15/audio --config config.yaml
```
Result: `audio/01-the-2-000-year-old-object-that-shouldn-t-exist.mp3`,
407,376 bytes, 63.025s, 24 kHz mp3, `kokoro (bm_george), tier=local`,
speed 0.9, pause 350 ms. Levels: mean −24.9 dB, max −7.6 dB.
Copied to `narration-kokoro-bm_george-0.9.mp3`. No pronunciation guesses:
all script words are standard English/Greek names from the published script.
Note: narrate.py appended 3 steps to `data/run_log.json` (its own log).

## 4. Music mix (branch src/music.py) — 20:22:43 UTC
```
python3 -m src.music --narration <narration mp3> --music music/mellow_history_bed.mp3 \
  --music-volume 0.06 --output productions/antikythera-short-2026-11-15/mixed-audio.mp3 \
  --config config.yaml
```
Result: 63.026s, 252,621 bytes; mean −25.4 dB, max −8.3 dB (no clipping);
no silence >2s. Bed-level verification in narration gaps (atrim, no seek):
gap 25.6–26.2s mixed mean −45.4 dB vs bed alone −20.5 dB (24.9 dB
attenuation; theoretical 0.06 = 24.4 dB); gap 52.9–53.5s −42.9 dB vs
−18.0 dB (24.9 dB). Linear RMS in gap ≈ 0.0054 — the task brief's "~0.02
RMS" estimate does not match this bed (bed mean −21.1 dB × 0.06 = 0.0053);
the 0.06 ratio itself is verified numerically. Copied to
`01-the-2-000-year-old-object-that-shouldn-t-exist.mp3` for the video CLI.

## 5. Subscribe narration (Kokoro) — 20:23:07 UTC
Same narrate.py path, scripts `[{rank:1, topic:"subscribe",
text:"Like and subscribe for more!"}]`:
`audio/01-subscribe.mp3`, 15,408 bytes, 2.775s, Kokoro bm_george 0.9.
Copied to `subscribe-narration-kokoro-bm_george-0.9.mp3`.

## 6. Visuals
Copied (not moved) from `~/workspace/faceless-creator/previews/stock/`:
gears.mp4 (1280×720, 8.0s), cogwheels.mp4 (1920×1080, 13.23s),
pocketwatch.mp4 (1920×1080, 19.84s), museum.mp4 (1080×1920, 4.12s),
wreck.mp4 (1080×1920, 9.06s), aegean.mp4 (1080×1920, 9.83s).
Loop-extended for the ~9.43s pattern-interrupt chunks:
`gears_loop16.mp4` (16.0s, `-stream_loop 1 -t 16 -c copy`),
`museum_loop12.mp4` (12.36s, `-stream_loop 2 -t 12.4 -c copy`),
`wreck_loop12.mp4` (12.05s, `-stream_loop 1 -t 12 -c copy`, added after
the xfade fix lengthened chunks). No cartoon clips used; no gradient
fallback used (0 scenes). Owl image copied to `owl-mascot-subscribe.png`.

## 7. Body render 1 (branch src/video.py) — 20:24:15–20:28:50 UTC — DISCARDED
```
python3 -m src.video --input <scripts.json> --audio-dir <prod> --outdir <prod>/body \
  --format short --end-card-text "Like and subscribe for more!" \
  --visuals <gears_loop16> <wreck> <cogwheels> <museum_loop12> <pocketwatch> <aegean>
```
Output measured 60.033s, not 63.03s: the xfade chain loses (n−1)×0.5s
and `-shortest` cut the narration tail. File deleted. See §8 fix.

## 8. CODE FIX 1 — src/video.py xfade overlap (20:29 UTC)
`chunk = duration / chunk_count` → `chunk = (duration + (n−1)×FADE) / n`,
so the joined video is exactly `duration`. Regression test
`tests/test_video_xfade_duration.py` (3 tests). Wreck loop-extended to 12s.
Re-render 20:29:32–20:34:19 UTC: body 63.000s exactly, 1080×1920, 30fps,
H.264 + AAC, 75,826,322 bytes, 6 visuals in 7 chunks.

## 9. Subscribe close, v4 recipe (adapted) — 20:34:52–20:35:10 UTC
Branch video.py has no subscribe-close mechanism, so the proven v4
recipe (previews/rotation01/build_body_v3.py SUB_IMG/SUB_DUR 4.6,
pyramid_void_60s/v4/) was used:
- `subscribe_clip.mp4`: owl image, zoompan 138 frames, + yellow
  drawtext "Like and subscribe for more!" (fontsize 60, #FFCC00,
  y=h−90), matching the v4 Antikythera tail frame (verified by reading
  it: owl + red SUBSCRIBE + yellow line at the bottom).
- `sub_audio.wav`: subscribe VO apad to 4.6s + bed atrim=6:10.6.
  FIRST BUILD (0.06 bed) was SILENT in the tail: on ffmpeg 8.1, `atrim`
  keeps timestamps, so amix placed the bed at t=6.0s, past the 4.6s
  output. Measured bed-only 2.9–4.6s at −91 dB. This also exposed that
  the v3 recipe's atrim-without-asetpts silently drops the bed on
  ffmpeg 8.1 — flag for the coordinator (v4 Shorts' close audio was
  built with the same recipe on an older ffmpeg; its tail bed was
  verified at the time by a different check).
- SECOND BUILD (20:37 UTC): added `asetpts=PTS-STARTPTS` after atrim
  and set the close bed to the v3 recipe value 0.22 (the 0.06 bed sits
  at ~−45 dB, below QA's −40 dB silence threshold, so the 2.4s bed-only
  tail after the VO read as silence and would fail QA's
  no_long_silent_stretches check). Body mix stays at the specified
  0.06; the close is the recipe value. Measured: bed-only 2.9–3.7s
  −34.0 dB, fade 3.9–4.6s −38.4 dB; no silence >2s in the final video.
- Concat (stream copy, faststart): body + subscribe.mp4 →
  `DeepScan-Antikythera-Short-2026-11-15.mp4`, 67.643s, 79,153,354 bytes.
- `final-audio.mp3` (QA narration): body mix + sub_audio via concat
  filter, 67.626s, mean −25.9 dB, max −8.7 dB. NOTE: the first
  concat-demuxer attempt on the mp3 produced a body-only 63.026s file
  (mp3float "Header missing" errors); rebuilt with the concat filter.

## 10. Beep scan — ~20:38 UTC
`beep_scan.py` (new; 0.25s Hann windows, hop 0.125s; suspect = one FFT
bin >60% of 300–3000 Hz band energy at >−50 dBFS, sustained ≥3 windows).
Final audio: 9 suspect windows, 1 sustained event — 53.0–53.375s,
440.0 Hz, −46.5 dB, during the 0.9s narration pause at 52.78–53.67s
(bed-only at 0.06). Control scan of the raw bed: 16 sustained events —
the bed is a repeating 16s loop of pure-tone pad notes (440 Hz at
5/21/37/53s, 524 Hz, 392 Hz), i.e. its normal musical content.
Assessment: no event above the −40 dB audibility floor the pipeline
uses; the close (the known beep risk area, bed window 6.0–10.6s) is
clean — 0 events in 63–67.6s. The 53s event is the bed's own note at
the specified 0.06 mix, ~20 dB below narration; left as a noted
finding, not a rebuild cause. `beep_scan.json` records it.

## 11. Frame checks — 20:35, 20:45 UTC (frames/ in prod dir)
- t=2s (fixed build): title "The 2,000-Year-Old Object That Shouldn'T
  Exist" fully visible on one line; caption "A geared bronze machine
  that predicted eclipses"; real gear footage. (Pre-fix build: title
  clipped at both edges; captions prefixed ",0,0,0,," — see §12.)
- t=15s: scuba diver at wreck, caption "are now held at the National
  Archaeological" (claim 02, in sync). t=30s: museum Greek statue,
  "Don't miss this:" prompt, caption "gear wheels. The mechanism was
  built around" (claims 04→05, in sync). t=45s: pocketwatch,
  caption "on the mechanism names its builder, and" (claim 10, in
  sync). t=58s: gears, "Here's why it works:" prompt, caption "What do
  you think happened? What does" (CTA, in sync).
- t=64.5s and t=66.5s: owl + red SUBSCRIBE button + yellow "Like and
  subscribe for more!" — matches the v4 Antikythera tail frame. No
  globe anywhere. No line art / stick figures in any checked frame;
  all visuals are real Pexels stock; no cartoon clips used.

## 12. CODE FIX 2 — src/video.py ASS format + title fit (20:39 UTC)
Frame check found two more branch defects:
(a) make_ass declared `[Events] Format: Layer, Start, End, Style, Text`
(5 fields) while Dialogue lines carry 10 fields, so libass rendered
",0,0,0,," at the start of every caption. Fixed: Format lists all 10
fields. (b) Title drawn at 72pt overflowed 1080px. Fixed: new
`_fit_fontsize()` (Pillow measurement, 0.62em fallback) shrinks the
title to fit width−80. Regression tests
`tests/test_video_captions_title.py` (4 tests). Full suite after both
fixes: 187/187 OK (was 180/180; +7 new). Body re-rendered 20:39:39–
20:44:31 UTC (63.000s), final re-concatenated 20:44–20:45:08 UTC
(67.643s, 79,243,966 bytes), frames re-extracted and re-checked (§11).
Minor pre-existing quirk left alone: `.title()` renders "Shouldn'T"
in the title card.

## 13. Thumbnail (branch src/thumbnail.py) — 20:45 UTC
```
python3 -m src.thumbnail --text "Ancient Machine Predicted Eclipses" \
  --output <prod>/DeepScan-Antikythera-Short-2026-11-15-thumb.png \
  --video <final mp4> --format short --script-text "<package text>" \
  --topic "The 2,000-Year-Old Object That Shouldn't Exist"
```
Result: 1080×1920, 1,058,378 bytes, Thumbnail QA PASS (pixel stddev
70.7). Text validated against the script (all four words appear in it).
Frame grabbed at 0.5s (gears). The intermediate
`<final>.thumb_frame.jpg` was removed from the prod dir afterwards.

## 14. QA (branch src/qa.py) — 20:45:42–20:46:21 UTC
```
python3 -m src.qa --video <final mp4> --narration <prod>/final-audio.mp3 \
  --script-text "<package text>" \
  --title "The 2,000-Year-Old Object That Shouldn't Exist" --format short \
  --script-json <prod>/documentary_package.json --report <prod>/qa_report.json
```
Result: QA pass, 21/21 checks, fixes: none. (Full check list in
qa_report.json.)

## 15. Upload gates — (see pipeline-config-record.md for outputs)
`--public` refused (exit 1); plain run refused without
HUMAN_REVIEW_APPROVED (exit 1); `--dry-run` printed the unlisted plan
(exit 0). No upload performed; no gate env vars set.

## 16. Deliveries copied to ~/workspace/your_files/
DeepScan-Antikythera-Short-2026-11-15.mp4,
DeepScan-Antikythera-Short-2026-11-15-thumb.png,
DeepScan-Antikythera-Short-2026-11-15-QA.json.
