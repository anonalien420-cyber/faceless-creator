# Production log — Deep Scan Antikythera Short v2 (audio + subtitle refinement), 2026-11-16

All times UTC. Work tree: `~/workspace/faceless-creator-branch/` (branch
`feature/deep-scan-evidence-engine`, head `4f72304b1` at start). No push
yet, no `.github/workflows/` touch, no `git` run, no upload, no workflow
trigger. No secrets used, copied, or set. Visuals APPROVED — reused
unchanged; only audio and subtitles were refined.

## 0. Baseline (v1, 2026-11-15)
- `productions/antikythera-short-2026-11-15/DeepScan-Antikythera-Short-2026-11-15.mp4`
  67.643s, 1080×1920, 30fps, QA 21/21 PASS, sha256 in v1 log.
- Body narration 63.025s, Kokoro bm_george 0.9, bed at 0.06.
- v1 captions: 22 lines, 7-word uniform chunks, mixed case.
- Known beep-scan event: 53.0–53.4s, 440 Hz, −46.5 dB (bed pad note,
  below the −40 dB floor).

## 1. Pronunciation audit (faster-whisper small + medium, word timestamps)
- Full-pass transcription of the v1 body narration matched the script
  word-for-word EXCEPT "Valerios Stais studied it" (~23.5–25.2s),
  heard as "Valerio's styes studded it".
- Second opinion (parent's run, isolated 22–26.5s clip): small heard
  "Valerio Steyce studied it"; medium heard "valerio's styes studded
  it". Both models hear "Stais" as one-syllable "Steyce/styes" (like
  "stays"), not two-syllable Greek STAH-ees. Models disagree on
  "studied" vs "studded" — treated as uncertain.
- Kokoro G2P check (misaki, British pipeline): "Stais" → unknown
  phonemes (grapheme fallback → the "styes" sound); "Valerios" →
  unknown; "Antikythera" → unknown (yet rendered recognisably);
  "studied" → stˈʌdɪd CORRECT (so "studded" is a Whisper
  near-homophone artifact, not a TTS error); "BCE" → letter names;
  "Athens" → ˈaθɪnz; "Saros" → sˈɛːɹɒs; "Metonic" → mɛtˈɒnɪk — all
  correct.
- Kokoro respelling experiments (bm_george 0.9, both Whisper models):
  "Stais" → "skies"/"styes" (wrong); "Star-ees"/"Stah-ees"/"Sta-ees" →
  "stories" (wrong); "Stah ees" → "Star-Ease"/"star ease" (BOTH models
  agree, two syllables, right vowels); "Stah eess" → "Star East"
  (wrong); "Stah iss" → "Star-Is" (short vowel). Winner: "Stah ees".
  Caveat: final consonant is voiced /z/ rather than Greek /s/
  ("Stah eess" was tested to fix that and heard as "Star East" — worse).
- Verified correct in v1 (no fix needed): Antikythera (8.56–9.34s),
  BCE, Athens, "1,400", "82 fragments", "30 bronze gear wheels",
  opening 12s word-for-word. Subscribe VO ("Like and subscribe for
  more!", 0.00–1.94s) — all 5 words correct.
- Pronunciation research (7 VERIFIED, 5 UNKNOWN, nothing guessed):
  VERIFIED — Antikythera, Saros, Metonic, Callippic, Cleopatra,
  Voynich (medium confidence, caveat noted), muon. UNKNOWN (checked, no
  reliable source) — Stais, Valerios, Exeligmos, Taposiris Magna,
  ScanPyramids. Stais/Valerios IPA in the dictionary is derived from
  the regular Modern Greek reading of the cited spellings (Στάης →
  /ˈsta.is/; Βαλέριος → /vaˈlerios/), NOT from a standalone IPA/audio
  dictionary source; the dictionary notes this explicitly.

## 2. Pronunciation dictionary (new, repo)
- `data/pronunciation_dictionary.json` — 14 entries (11 verified,
  3 unknown: Exeligmos, Taposiris Magna, ScanPyramids). Mirrors the
  vid_upgrade schema (name, aliases, category, confidence, ipa,
  kokoro_text, respelling, source, ssml_phoneme, status, notes) +
  meta block with the NEVER-invent rule.
- Only ONE entry has a kokoro_text respelling: Stais → "Stah ees"
  (empirically verified by both Whisper models). All other verified
  entries have kokoro_text null (current rendering already correct).
- `src/pronunciation.py` — load_dictionary(), verified_entries(),
  apply_pronunciation() (longest-form-first, word-boundary aware,
  case-insensitive, possessives match), flag_unknown(). Applied ONLY
  in memory at narration time; ledger, script, and subtitles keep the
  correct written forms.
- `tests/test_pronunciation.py` — lookup, respelling, unknown-word
  behaviour, no-op on ordinary words.

## 3. Pacing — what was tried, what worked, what was reverted
- Ellipsis probe (2026-11-16): "..." as a standalone chunk does NOT
  lengthen Kokoro's inter-sentence pause — total durations identical
  (plain 6.86s, "..." 6.90s, "......" 6.84s, comma+"..." 6.70s).
  Conclusion: "..." pause markers are inert for Kokoro (they only
  affect engines that read punctuation). The `humanize_text` plain
  markers were extended to "? ", "! ", ": " anyway (correct for
  Edge/pyttsx3; harmless for Kokoro) and the docstring corrected.
- Per-sentence synthesis (TRIED AND REVERTED): synthesizing one
  sentence per Kokoro call made Kokoro speak ~20% slower — the same
  151 words rendered as 80.425s instead of 63.025s (+17.4s, blowing
  the video duration budget). Reverted to the single-call path (v1
  behaviour); the failure is documented in narrate_kokoro's docstring
  and in the tests (KokoroSingleCallTests).
- Working mechanism: `sentence_pauses()` (hook +0.3s, between closing
  questions +0.2s) + `src/narrate.py:insert_silence()` (inserts exact
  digital silence at measured times, ffmpeg + numpy + soundfile).
  Insertion points are anchored in the REAL silence after each
  boundary word (ffmpeg silencedetect), not in Whisper's word-end
  estimate — the first attempt inserted at Whisper's word end (6.16s)
  and split the vowel tail of "ago." (a 0.3s phantom silence appeared
  inside the word); re-anchoring to the silence start (6.23s) fixed
  it. Production driver: `apply_pacing.py` (transcribe → align →
  anchor → insert → shift timings analytically).
- Measured beats in the final narration: hook gap 0.445s → 0.745s
  (insert +0.3s at 6.23s); questions gap lengthened +0.2s at 59.91s.
  All other sentence-boundary gaps unchanged (0.54–0.80s).

## 4. Narration (Kokoro, single call, dictionary applied)
```
TMPDIR=~/workspace/tmp_pip ~/workspace/tts_venv/bin/python -m src.narrate \
  --input productions/antikythera-short-2026-11-15-v2/scripts.json \
  --outdir productions/antikythera-short-2026-11-15-v2/audio --config config.yaml
```
- Raw v2 narration: 63.100s (v1: 63.025s; +0.075s from the two-syllable
  "Stah ees"), 404,616 bytes, Kokoro bm_george 0.9.
  "Pronunciation respellings applied: Stais".
- After pacing insertion: `audio/01-...-final.mp3`, 63.600s, 509,421
  bytes. Raw copy kept as `narration-kokoro-bm_george-0.9.mp3`.
- Verification (faster-whisper small, raw narration): 153 words heard;
  diff vs script shows ONLY number-form differences ("two thousand"→
  "2 000", "thirty"→"30", "1400"→"1 400") and "Stais"→"star ease"
  (two syllables — the fix working). "studied" heard as "studded"
  in the raw pass (Whisper near-homophone; Kokoro G2P confirms
  "studied" is correct — see §1).
- Final-narration Stais region (shifted timings): "star" 24.26–24.66,
  "ease" 24.66–25.12 — two syllables, in sync with the caption
  "MUSEUM'S VALERIOS STAIS" (23.14–24.99s).

## 5. Music mix (branch src/music.py) — 06:0x UTC
```
python3 -m src.music --narration <final narration> --music music/mellow_history_bed.mp3 \
  --music-volume 0.06 --output <prod>/mixed-audio.mp3 --config config.yaml
```
Result: 63.600s, 254,829 bytes; bed at 0.06 (same as v1).
Copied to `01-the-2-000-year-old-object-that-shouldn-t-exist.mp3` for
the video CLI.

## 6. Subscribe close — REUSED byte-identical from v1
- `subscribe.mp4` md5 36fd18c1870571bf80854add4d261944 (matches v1);
  `sub_audio.wav` md5 2c47a0a7334b165b6ed2edbc7ca7ec35 (matches v1).
- Subscribe VO re-transcribed for the close captions: Like 0.00–0.52,
  and 0.52–0.76, subscribe 0.76–1.22, for 1.22–1.70, more. 1.70–1.94
  — all 5 words correct, no diff.
- Close captions are VO-timed in the sidecar ASS (see §8); the close
  clip itself is unchanged (yellow drawtext line still shows the full
  line for the whole 4.6s, as in v1).

## 7. Body render (branch src/video.py, timed captions)
```
python3 -m src.video --input <v2>/scripts.json --audio-dir <v2> --outdir <v2>/body \
  --format short --end-card-text "Like and subscribe for more!" \
  --visuals <gears_loop16> <wreck> <cogwheels> <museum_loop12> <pocketwatch> <aegean> \
  --word-timings <v2>/word_timings_final.json
```
Output: body 63.566s, 1080×1920, 30fps, H.264+AAC, 76,749,382 bytes,
6 visuals in 7 chunks (same order as v1). ASS: 51 Dialogue lines
(v1: 22), all ≤3 words, UPPERCASE, monotonic, no overlap (verified
by script). Title card UNTOUCHED — "Shouldn'T" quirk still present
(visual, approved, left alone).
- New `--word-timings` CLI option + `build_video(word_timings=...)`:
  captions follow the spoken words via `align_script_to_timings()`
  (difflib on canonical tokens; numbers collapse so "two thousand"
  aligns with "2,000"; misheard blocks share the span evenly).
  Legacy path (no word_timings) unchanged.

## 8. Final assembly
- Concat (stream copy, faststart): body + subscribe.mp4 →
  `DeepScan-Antikythera-Short-2026-11-15-v2.mp4`, 68.209s,
  80,076,448 bytes, sha256
  8f235cf94dee3a8a4b01d24908a77df12e90e6122ad23fcb4a3db834bd629dfa.
- `final-audio.mp3` (QA narration): mixed-audio + sub_audio via the
  CONCAT FILTER (the concat demuxer failed on mp3 with "Header
  missing" and produced a body-only file — same as v1 §9), 68.200s,
  546,285 bytes.
- Sidecar ASS `DeepScan-Antikythera-Short-2026-11-15-v2.mp4.ass`:
  body ASS (51 lines) + 2 VO-timed close lines, offset by the body
  duration 63.566s: "LIKE AND SUBSCRIBE" 63.57–64.79, "FOR MORE!"
  64.79–65.51. (v1 used uniform splits of the whole 4.6s close.)

## 9. Thumbnail (branch src/thumbnail.py)
Same command as v1 (text "Ancient Machine Predicted Eclipses").
Result: 1080×1920, 1,044,516 bytes, Thumbnail QA PASS (pixel stddev
70.6; v1: 70.7 — same gears frame at 0.5s). md5 differs from v1's
thumb (different encode + uppercase caption at 0.5s).

## 10. QA (branch src/qa.py)
```
python3 -m src.qa --video <v2 final> --narration <v2>/final-audio.mp3 \
  --script-text "<narration.txt>" \
  --title "The 2,000-Year-Old Object That Shouldn't Exist" --format short \
  --script-json <v2>/documentary_package.json --report <v2>/qa_report.json
```
Result: QA PASS, 21/21 checks, fixes: none. (Full check list in
qa_report.json.) Notable: video 68.2s vs narration 68.2s; mean
−25.9 dB, max −9.7 dB (no clipping); 0 black/silent stretches >2s;
first 3s not black; ASS present; ledger validates; claims match the
reviewed ledger; ends with the open viewer question.

## 11. Beep scan
`beep_scan.py` (copied from v1) on final-audio.mp3: 9 suspect windows,
1 sustained event — 53.125–53.75s, 440.0 Hz, −46.7 dB. SAME event as
v1 (53.0–53.4s, 440 Hz, −46.5 dB): the bed's own pad note in a
narration pause, shifted +0.3s by the hook beat, still ~7 dB below
the −40 dB floor. Close (63–68.2s): 0 events. Assessment unchanged
from v1: noted finding, not a rebuild cause.

## 12. Frame checks (frames/ in prod dir)
- t=2s: title fully visible ("Shouldn'T" quirk intact); real gear
  footage; caption "MACHINE THAT PREDICTED" (uppercase, 3 words).
- t=15s: scuba diver at wreck; caption "NOW HELD AT" (in sync).
- t=30s: museum Greek statue; "Don't miss this:" prompt; caption
  "BRONZE GEAR WHEELS." (in sync).
- t=45s: pocketwatch; caption "UNKNOWN: NO / INSCRIPTION" (3-word
  frame wraps to 2 lines at 72pt — fully legible, not clipped).
- t=58s: gears; "Here's why it works:" prompt; caption "WHAT REMAIN.
  WHAT" (CTA in sync).
- t=64.5s and t=66.5s: owl + red SUBSCRIBE + yellow "Like and
  subscribe for more!" — the reused v1 close clip. No globe anywhere.
  No line art / stick figures in any checked frame; all visuals are
  the same real Pexels stock clips in the same order as v1.
- Visual-order check: gears → wreck → cogwheels → museum →
  pocketwatch → aegean, identical to v1. (Chunk boundaries shift
  ~0.08s because the body is 0.566s longer; frames at the same wall
  time show the same clip at a slightly different offset — expected.)

## 13. Upload gates
Not re-run for v2 (no code change to src/upload.py or the gates;
v1's gate checks stand). No upload performed; no gate env vars set.

## 14. Deliveries copied to ~/workspace/your_files/
DeepScan-Antikythera-Short-2026-11-15-v2.mp4,
DeepScan-Antikythera-Short-2026-11-15-v2-thumb.png,
DeepScan-Antikythera-Short-2026-11-15-v2-QA.json.

## 15. Code changes (for the PR branch commit)
- NEW `data/pronunciation_dictionary.json` (14 entries) +
  `src/pronunciation.py` + `tests/test_pronunciation.py`.
- `src/narrate.py`: dictionary wiring (--pronunciation-dictionary,
  applied in memory, prints applied names + unknown flags);
  `humanize_text` plain pauses extended to "? ", "! ", ": ";
  `sentence_pauses()` (hook +0.3s, closing questions +0.2s);
  `insert_silence()` (exact silence insertion at measured times);
  `narrate_kokoro` REVERTED to single-call (per-sentence variant
  documented as slower — see §3).
- `src/video.py`: `align_script_to_timings()` + `_canonical_tokens()`
  + `_number_value()`; `make_ass(word_timings=..., extra_captions=...)`;
  `build_video(word_timings=...)`; `--word-timings` CLI option.
- `tests/test_narration_audio.py`: SentencePausesTests,
  KokoroSingleCallTests, InsertSilenceTests, humanize ?/: test.
- `tests/test_video_captions_timing.py` (new): alignment + timed ASS.
- Production text evidence in this dir (production log, pipeline
  config record, QA report, ASS, narration text, word timings).
- MP4 stays OUT of the repo by design.
