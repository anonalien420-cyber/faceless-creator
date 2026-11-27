# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/), and the project
adheres to semantic versioning.

## [1.2.0] — 2026-11-27

Tier 1 feedback-loop + trust enhancements (the highest-leverage next
additions). $0 default preserved; all opt-in capabilities degrade
gracefully.

### Added
- **Retention analytics loop (`src/analytics.py`).** Pulls average view
  duration / average view percentage / estimated minutes watched from the
  YouTube **Analytics API** (free, opt-in `analytics_enabled`, needs the
  `youtube-analytics.readonly` scope) into the weekly review, so
  hook/length/pacing corrections are driven by watch time, not just views.
  Falls back to manual/Data-API stats when unavailable.
- **Upload verification + video-ID feedback.** After a real upload,
  `upload.py` polls YouTube until processing finishes (`verify_processed`)
  and records the `video_id`, privacy, publishAt, and processing status to
  `data/upload_feedback.json`. A failed/rejected upload is never logged as
  published. The run manifest now links each output to its published
  video_id, closing the review loop.
- **On-screen source citations.** History-mystery videos show the verified
  source as a branded badge when the shock hook / a KNOWN fact is on screen
  (`show_citations`, default true). Only real, non-placeholder sources are
  shown — a visible trust signal that separates accurate content from
  misinformation.

### Tests
- 16 new regressions (`tests/test_feedback_loop.py`): analytics parsing +
  enrichment, upload status interpretation + verification polling +
  feedback append, citation emission + placeholder rejection + render,
  and Tier 1 config validation. Suite now 81 tests, green under stdlib and
  Pillow/PyYAML; ruff clean.

## [1.1.0] — 2026-11-27

The "more efficient, professional, high-quality production" roadmap,
implemented in three phases plus polish. The $0-budget default is
unchanged: every paid capability stays an opt-in tier, and every new
stage still passes the accuracy/QA guardrails.

### Added — Phase 1: production polish
- **Word-synced karaoke captions.** `narrate.py` streams edge-tts
  `WordBoundary` metadata into a `<audio>.timings.json` sidecar (CLI
  fallback converts SRT sentence cues). `video.make_ass` consumes it to
  highlight the active word in the brand accent, synced to the voice.
- **Shorts-safe caption zone.** Captions are kept out of the bottom ~25%
  of vertical video so the Shorts UI never covers them.
- **Audio mastering.** `music.py` masters every track to a target
  loudness (`loudnorm I=-14:TP=-1.5:LRA=11`), ducks the music bed under
  the narration (`sidechaincompress`), and adds 0.5s fade-in/out.
- **Brand kit.** A `brand:` config block (accent colours, font, logo,
  watermark) drives title cards, end cards, lower-thirds, captions,
  watermark, and thumbnails for one consistent channel look.

### Added — Phase 2: quality depth
- **Free research (`src/research.py`).** Wikipedia REST + Wikidata (no
  key) yield verified facts and real `{title, url}` sources that feed the
  KNOWN tier and a sourced shock hook. Optional LLM draft tier
  (template → local → api) still flows through `drop_unverified` + QA.
- **Scene-matched B-roll.** Per-section keywords fetch stock per scene
  (with a key); falls back to the shared visual pool without one.
- **Topic memory.** `data/topic_history.json` prevents repeating topics
  across days (`topic_memory_days`).
- **Hook A/B variants.** All four hook phrasings are generated; the
  views-weighted winner from `review.py` performance data is selected.
- **Trend velocity scoring.** Views-per-day velocity + a tuned
  exponential recency decay rank fast-rising content over stale counts.

### Added — Phase 3: engine + developer experience
- **In-process orchestration.** `run.py --in-process` calls each stage's
  `main()` directly (no per-stage interpreter startup); subprocess
  isolation remains the default.
- **Parallel renders + concurrent downloads.** `video.py` renders videos
  in a thread pool and downloads stock concurrently.
- **Content-hash caching.** Unchanged script + voice + visuals skip
  re-TTS and re-render (`data/cache.json`); ffprobe results are memoized.
- **Per-run manifest.** `data/run_manifest.json` records render time, QA
  pass rate, and upload status.
- **Typed models.** `src/models.py` dataclasses (Script, Scene,
  VideoReport, Brand, Source) round-trip with the existing dict APIs.
- **Unified CLI.** `faceless <stage>` dispatches to every module.
- **Packaging.** `pyproject.toml`, `requirements.lock` (pip-tools),
  `Dockerfile` (ffmpeg + DejaVu + deps), `.pre-commit-config.yaml`.
- **Config.** Full YAML via PyYAML when installed (stdlib fallback still
  works), plus fail-fast `validate_config`.
- **CI.** Ruff lint gate, advisory mypy, and coverage in `tests.yml`.
- **Docs.** Split into `docs/` (setup, architecture, operations, content
  policy, roadmap).

### Added — polish
- Long-form **chapter title cards / section lower-thirds**.
- **Varied transitions** (zoom-punch on emphasis) instead of all-crossfade.
- **Saliency-aware thumbnail focal crop** + brand template + tighter
  typography.

### Fixed
- `research.py` CLI used `args.llm-tier` (parsed as subtraction) — now
  `args.llm_tier`.
- Removed unused imports/variables flagged by ruff; `raise ... from exc`
  in the upload import guard.

## [1.0.1] — 2026-11-27

The 24-item review fix pass (PR #9): caption/hook layout, QA detectors,
narration rate/pacing, script length/CTA integrity, music level, scheduler
stagger, config parsing, upload privacy/scheduling, trend sourcing, SEO
titles, thumbnail truth-check, CI test workflow, and README claim fixes.
29 regression tests added.
