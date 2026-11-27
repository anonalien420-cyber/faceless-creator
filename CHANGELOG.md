# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/), and the project
adheres to semantic versioning.

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
