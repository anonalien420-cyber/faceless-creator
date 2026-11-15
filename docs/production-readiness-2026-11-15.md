# Deep Scan production pipeline — status 2026-11-15 (finish pass)

Branch: `feature/deep-scan-evidence-engine`, base head `44c0ab7e`
("Fix music bed safeguard test for tracked in-house asset",
2026-11-13T22:38Z). PR #1, OPEN, DRAFT, not merged.
This pass continues from the Nov 12 close-out
(`docs/production-readiness-2026-11-12.md`): the Nov 12 verdict was
NOT production-ready (no reviewed claims, no real video, unpushed).
This document records what the Nov 15 finish pass changed and what
is still open. Nothing here is merged; nothing was published; no
video was uploaded.

## 1. What changed in this pass

### Evidence ledger: REAL, human-reviewed (was: BLOCKED, no reviewed claims)
- `data/evidence_ledger.json` (new): 12 Antikythera claims
  (10 KNOWN, 1 DEBATED, 1 UNKNOWN), 6 sources, all APPROVED,
  reviewer Kristian, reviewed 2026-11-03/04/05. Transcription of
  Kristian's existing human review of the published long-form
  (YouTube `k_wGkEfT5QI`, Public 2026-11-06) — NOT self-approval.
  Provenance field states this explicitly.
  Sources: Britannica, Nature 2006 Freeth et al.
  (doi:10.1038/nature05357), Sci Rep 2021 UCL
  (doi:10.1038/s41598-021-84310-w), NAM Athens, thesea.org,
  Heritage 2021 Efstathiou et al. (doi:10.3390/heritage4040211).
  Validation: `src.evidence` PASS; `src.verification` report PASS.
- `docs/antikythera-ledger-provenance.md` (new): source of truth,
  review-date table, source table, validation results, deliberate
  omissions (wreck depth ~45 m — no cited source; Callippic /
  Exeligmos dials — unconfirmed by the cited set; "1,500 years"
  variant rejected by the blueprint's own accuracy annotation).
- `data/review_packet_antikythera.md` / `.json` (new, generated):
  review packet for the record.
- The Great Pyramid ledger Echo described overnight Nov 13–14 was
  confirmed non-existent: not on this branch, not on
  `phase2/source-taxonomy-schema-v2`, not in the AI Command Center
  Drive folder, not locally. No Pyramid claims recorded.

### Claim extraction (Phase 2D): BUILT (was: unbuilt)
- `src/claim_extraction.py` (new, stdlib only): extracts candidate
  claims from already-filtered discovery sources only; tier
  suggestion defaults UNKNOWN; everything returned UNREVIEWED with
  blank reviewer fields and `include_in_script: False`. Minimal
  wiring: `src/review_packet.py` gained an optional
  `extracted_claims` parameter; no other pipeline file changed.
- `tests/test_claim_extraction.py` (new): 20 fixture-based tests.
- `tests/test_evidence_ledger.py` (new): 14 tests against the real
  ledger (gate, tiers, verification, documentary short build).

### Pipeline hardening: 7 known issues from Nov 12 §5 — ALL FIXED
- `src/review.py`: no longer writes `review_*` keys into
  `config.yaml`; adjustments go to `data/review_adjustments.json`.
- `src/upload.py`: dead scheduled-publish `publishAt` branch removed;
  `plan()` raises `ValueError` on any `publish_at`; token refresh
  write sets mode 600 via new `_save_token()`.
- `src/music.py`: `amix normalize=0` (no ~6 dB halving); bed loops
  (`-stream_loop -1`) to cover narration longer than the 64 s bed.
  Verified numerically with a real mix.
- `src/narrate.py`: `validate_speed()` (0.5–2.0), enforced in CLI,
  config, and `narrate_kokoro()`; no silent clamping.
- `src/visuals.py`: `scene_fingerprint()` now includes sorted
  `claim_ids` + `source_ids`; a claim/source change regenerates
  instead of reusing the wrong visual.
- `src/run.py`: `script_command()` wires the documentary path for
  the history-mystery niche; `scripts:long` / `scripts:short` now
  emit the evidence-led command. Proven by a test that runs the exact
  emitted command through `script.main`.
- `tests/test_pipeline_hardening.py` (new): 22 tests.
- `src/config.py`: stale comment (lines 65–66) corrected — review.py
  no longer writes into config.yaml.

### ComfyUI: still BLOCKED (no host), fallback verified real
- No reachable host: `COMFYUI_BASE_URL` / `COMFYUI_IMAGE_WORKFLOW`
  unset, nothing listening on 8188/8189, no process, no config keys.
  No real exported API workflow JSON exists anywhere; the fixture is
  a synthetic stand-in and was not used as a live workflow.
- Loud failure proven: `tests/test_visuals_comfyui.py` 13/13,
  including `test_unreachable_host_fails_loudly`.
- Fallback visuals verified real: Pexels stock in the main copy
  (`previews/stock/`, 12 files probed, all decode OK); full-colour
  cartoon builders `src/show.py` / `src/mascot.py` exist in the main
  copy only, absent from this branch tree.
- Exact requirements for live verification: (1) reachable host URL
  as `COMFYUI_BASE_URL`; (2) real exported API-format workflow JSON
  with `{{PROMPT}}` / `{{SEED}}` in real node inputs;
  (3) the named models installed on that host.

### Real video: PRODUCED (was: synthetic-only E2E)
- `productions/antikythera-short-2026-11-15/` — one real 60 s
  Antikythera Short, built end to end through the branch pipeline:
  documentary package (151 words, 7 claims, hook antikythera_01) →
  real Kokoro narration (bm_george, 0.9, 63.025 s) → real bed mix
  at 0.06 → real Pexels stock only (gears, wreck, cogwheels,
  museum, pocketwatch, aegean; gradient fallback: 0 scenes; no
  cartoon clips used) → owl subscribe-close (v4 recipe, 4.6 s) →
  ASS captions → render 1080×1920, 30 fps, H.264 + AAC, faststart.
- Final: `DeepScan-Antikythera-Short-2026-11-15.mp4`, 79,243,966
  bytes, 67.643 s (over the ~60 s target: the 151-word package at
  locked 0.9 speed renders 63.0 s of body; trimming words would
  break the evidence gate and speed is locked).
- QA: **21/21 PASS** (`qa_report.json`), including all accuracy
  checks (ledger valid, script rebuilds byte-for-byte from the
  ledger, shock hook sourced, ending open question, description
  sources valid).
- Thumbnail: `DeepScan-Antikythera-Short-2026-11-15-thumb.png`
  (1080×1920) via `src/thumbnail.py`; text "Ancient Machine
  Predicted Eclipses", validated against the script.
- Upload gates verified live: `--public` refused (exit 1),
  `--auto-public` refused, plain run refused without
  `HUMAN_REVIEW_APPROVED`, `--dry-run` exit 0 with unlisted plan.
  No upload performed.
- Two real pipeline bugs found by frame-checking and fixed, with
  regression tests: (1) `src/video.py` xfade truncation (n chunks
  lost (n−1)·0.5 s; first render 60.03 s cut ~3 s of narration) —
  `tests/test_video_xfade_duration.py` (3 tests). (2) ASS captions
  garbage + clipped title (Format line declared 5 fields, Dialogue
  lines carry 10; 45-char title at 72 pt overflowed) — Format fixed,
  `_fit_fontsize()` added — `tests/test_video_captions_title.py`
  (4 tests).
- Two close-audio defects found by measurement and fixed: the v3
  recipe's `atrim` without `asetpts` silently dropped the bed on
  ffmpeg 8.1 (tail −91 dB) — fixed with `asetpts=PTS-STARTPTS`;
  the close bed is 0.22 (v3 recipe value), not 0.06 — the 0.06 bed
  sits at ~−45 dB, below QA's −40 dB silence floor. Body mix stays
  at the specified 0.06. Flag: the shipped v4 Shorts' close audio
  was built with the same recipe on an older ffmpeg; their tails
  are worth a listen-check.
- Beep scan: 1 sustained event recorded, not hidden — 53.0–53.4 s,
  440 Hz, −46.5 dB: the bed's own pad note during a 0.9 s narration
  pause at 0.06 mix. No events above the −40 dB floor; the close
  is clean. (`beep_scan.json`)
- Known cosmetic quirks (in `production-log.md`): title card reads
  "Shouldn'T" (pre-existing branch `.title()` quirk); duration
  67.6 s vs ~60 s target (see above).

## 2. Test results (local, full suite)

`python3 -m unittest discover -s tests` → **187 tests, OK, 0 failures.**

| Suite | Tests |
|---|---|
| test_claim_extraction (new) | 20 |
| test_evidence_ledger (new) | 14 |
| test_pipeline_hardening (new) | 22 |
| test_video_xfade_duration (new) | 3 |
| test_video_captions_title (new) | 4 |
| test_visuals_comfyui | 13 |
| test_narration_audio | 27 |
| test_config_regressions | 13 |
| test_relevance | 14 |
| test_artifact_coverage | 15 |
| test_publishing_safeguards | 11 |
| test_qa_list_input | 5 |
| test_video_fallback_fps | 2 |
| pre-existing suites | 24 |

Baseline at the start of this pass: 124 tests (one failing —
the bed-existence test — because the binary bed was not in the
local tree; the bed file was already on the branch at dacf52f and
was copied into the local tree during this pass, closing that
failure).

## 3. Production-readiness bar (§A.5 of the Nov 10 audit) — updated

| Bar item | Status |
|---|---|
| Clean-runner `pip install` + every src module imports | STILL NOT PROVEN — pins verified downloadable only; no clean install run |
| Real long-form render (8–12 min, 1920×1080, chunk_count ≥ 3, both visual variants) with QA passing | NOT DONE — one real 60 s Short produced (this pass); no long-form render through the branch pipeline yet. Now unblocked in principle: the ledger exists and the documentary long path is wired. |
| Real narration (Kokoro bm_george 0.9 + real mellow bed) verified by listening | PARTLY — generated + mixed + numerically verified; human listen-check still owed (voice naturalness, bed balance). Narration + mix files are in `productions/antikythera-short-2026-11-15/`. |
| Real Unlisted upload via real OAuth token, HUMAN_REVIEW_APPROVED gate enforced, --public refused | NOT DONE — dry-run only; gate + refusal verified in code and CLI, no real upload (needs owner's go-ahead). |
| Full scheduled daily run on main completing 1 long + 2 Shorts | NOT DONE — impossible until PR #1 merges and reviewed claims cover a full day (the ledger now covers Antikythera only). |
| CI green on the actual merge commit + Dependabot live on main + independent reviewer approval + owner's upload-policy approval | NOT DONE — no merge, no reviewer, no policy call. CI on the new head: see §5. |
| At least one real-topic evidence pass (Great Pyramid E2E) | CHANGED — Great Pyramid ledger still does not exist anywhere; the real-topic E2E is now Antikythera (this pass), not Great Pyramid. |

**Verdict: still NOT production-ready per §A.5**, but the
material gaps closed in this pass: reviewed claims exist, a real
video was produced end to end with QA passing, the pipeline's
known issues are fixed, and the suite is 187/187. Remaining
human-gated items: narration listen-check, real Unlisted upload,
CI on the new head, independent reviewer, upload-policy approval.

## 4. PR state

- PR #1: OPEN, DRAFT, not merged. Head after this pass: see §5.
  https://github.com/anonalien420-cyber/faceless-creator/pull/1
- PR #5 (Phase A): OPEN, not merged, chained behind PR #1. Not
  touched.
- PR #3: still in conflict after PR #4 merged into its base; needs
  rebase or closure. Not touched.

## 5. Push + CI

(To be filled in by the coordinator after the push: commit SHAs,
CI run result on the new head.)

## 6. Files changed in this pass (local tree)

Modified: `src/config.py`, `src/music.py`, `src/narrate.py`,
`src/review.py`, `src/review_packet.py`, `src/run.py`,
`src/upload.py`, `src/video.py`, `src/visuals.py`, `README.md`,
`tests/test_narration_audio.py` (synced to branch head 44c0ab7e).
New: `src/claim_extraction.py`, `data/evidence_ledger.json`,
`data/review_packet_antikythera.md`, `data/review_packet_antikythera.json`,
`docs/antikythera-ledger-provenance.md`,
`docs/production-readiness-2026-11-15.md` (this file),
`tests/test_claim_extraction.py`, `tests/test_evidence_ledger.py`,
`tests/test_pipeline_hardening.py`,
`tests/test_video_xfade_duration.py`,
`tests/test_video_captions_title.py`,
`productions/antikythera-short-2026-11-15/` (production evidence;
binaries NOT pushed to the repo — see §7).
`music/mellow_history_bed.mp3` copied into the local tree (already
on the branch at dacf52f; not re-pushed).

## 7. What was deliberately NOT done

- The 79 MB finished MP4 was NOT committed to the repo (contents
  API / git history bloat; the daily.yml artifact step is the
  sanctioned preservation route for rendered videos). The MP4 is
  delivered from the local production dir and `~/workspace/your_files/`.
  Binary production intermediates (subscribe clips, audio stems,
  frames, owl PNG copy) were not pushed either.
- No real upload, no publish, no merge, no ready-for-review mark,
  no self-approval, no workflow triggered.
- No long-form render through the branch pipeline (see §3).
- No ComfyUI live verification (no host — see §1).
- No clean-runner `pip install` proof (see §3).
