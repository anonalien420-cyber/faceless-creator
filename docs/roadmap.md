# Production roadmap (implemented)

The "more efficient, professional, high-quality content and video
production" roadmap, delivered in three phases plus polish. Guiding
constraints, all preserved:

- **$0-budget default.** Paid capabilities are opt-in tiers mirroring the
  voice-tier pattern; nothing paid is required or default.
- **Accuracy/QA guardrails.** Every new stage still passes `drop_unverified`
  and the QA gates; a broken or unsourced video never uploads.
- **Tests stay green.** The existing suite passes and new behavior ships
  with regression tests; renders are verified with real ffmpeg.

## Phase 1 — quick wins (production polish)
- [x] Word-level timings from edge-tts `WordBoundary` written beside the
      audio; timed karaoke captions with active-word highlighting.
- [x] Captions kept out of the bottom ~25% (Shorts UI safe zone).
- [x] `loudnorm I=-14:TP=-1.5:LRA=11`, sidechain music ducking, 0.5s fades.
- [x] `brand:` config block driving title/end cards, lower-thirds,
      watermark, captions, and thumbnails.

## Phase 2 — quality depth
- [x] Scene-matched B-roll: per-section keywords, stock per scene, graceful
      fallback without a key/clip.
- [x] Free `src/research.py` (Wikipedia REST + Wikidata, no key) → verified
      facts + real `{title,url}` sources feeding KNOWN tier + shock hook.
- [x] Optional LLM draft tier (template → local → api), still through
      `drop_unverified` + QA.
- [x] `data/topic_history.json` topic memory (no repeats across days).
- [x] Hook variants selected from `review.py` performance data.
- [x] Trend scoring by views-per-day velocity + tuned recency decay.

## Phase 3 — engine + developer experience
- [x] In-process orchestration (`run.py --in-process`); subprocess default.
- [x] Parallel renders (thread pool) + concurrent stock downloads.
- [x] Content-hash caching to skip re-TTS/re-render; ffprobe cache; cheap
      resume after a failed stage.
- [x] PyYAML config (stdlib fallback) + fail-fast `validate_config`.
- [x] `pyproject.toml` + `requirements.lock` + unified `faceless` CLI.
- [x] ruff + mypy + pre-commit + coverage in `tests.yml`.
- [x] `Dockerfile` (ffmpeg + DejaVu + deps) for reproducible renders.
- [x] `src/models.py` dataclasses (Script/Scene/VideoReport/Brand/Source).
- [x] README split into `docs/` + `CHANGELOG.md`.
- [x] Per-run manifest metrics (render time, QA pass rate, upload status).

## Polish
- [x] Long-form chapter title cards + section lower-thirds.
- [x] Varied transitions (zoom-punch on emphasis) instead of all-crossfade.
- [x] Saliency-aware thumbnail focal crop + brand template + tighter
      typography.

## Tier 1 — feedback loop + trust (added in 1.2.0)
- [x] **Retention analytics loop** (`src/analytics.py`): YouTube Analytics
      API retention (avg view duration / percentage) feeds the weekly
      review so corrections are driven by watch time, not just views.
- [x] **Upload verification + video-ID feedback**: poll YouTube until
      processing finishes; record `video_id` + status to
      `data/upload_feedback.json` and the run manifest (closes the loop).
- [x] **On-screen source citations**: verified sources shown on screen for
      history videos (trust signal); only real, non-placeholder sources.

## Notes / deliberate scope decisions
- The subprocess log-merge remains for the default isolated path;
  `--in-process` avoids per-stage interpreter startups while sharing the
  same log/manifest.
- mypy runs advisory (the dict-heavy pipeline is incrementally typed);
  ruff lint is a hard gate.
- Optional YouTube thumbnail A/B API and segment-pre-render/concat for
  very long form are left as future opt-in enhancements; the current
  parallel render + caching already covers the daily cadence efficiently.
