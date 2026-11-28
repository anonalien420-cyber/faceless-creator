# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/), and the project
adheres to semantic versioning.

## [1.3.0] — 2026-11-27

Tier 2 (reach + learning) and Tier 3 (quality + operations) enhancements.
$0 default preserved; every paid/network capability stays opt-in and
degrades gracefully. Accuracy guardrails (`drop_unverified` + QA) and the
no-accidental-public-upload rule are unchanged.

### Added — Tier 2 (reach + learning)
- **Semantic topic dedupe (`src/similarity.py`).** Topic memory now skips
  paraphrases, not just exact repeats: a smooth TF-IDF cosine over content
  words (stopwords removed, crude stemming) flags near-duplicate topics
  (`topic_similarity_threshold`, default 0.6). Stdlib-only, offline, no
  model download. Precision-leaning so a distinct story ("lost city of
  Petra" vs "Atlantis") is never silently dropped.
- **Multi-language reach (`src/localize.py`).** Config `language` (BCP-47)
  picks that language's free edge-tts neural voice when no explicit voice
  is set, and the upload sets `snippet.defaultLanguage` /
  `defaultAudioLanguage` so a Spanish-narrated video is discoverable in
  Spanish. Optional `localization_tier: api` translates title/description
  into YouTube `localizations` (additive); the default `template` tier
  never machine-translates — a wrong translation is worse than none.
- **Learned publish hour (bandit-lite).** The weekly review learns the
  best publish hour per niche from your own views-weighted stats
  (`data/publish_hours.json`) when `publish_learning` is on. The scheduler
  exploits a learned hour only INSIDE an existing peak window and only
  after `publish_learning_min_samples` scored videos — one lucky upload
  never rewires the schedule, and learning never invents new windows.

### Added — Tier 3 (quality + operations)
- **`faceless doctor` (`src/doctor.py`).** One readiness report: Python,
  ffmpeg/ffprobe, DejaVu fonts, optional deps, config validation, optional
  API keys (presence only, never printed), and data-dir writability.
  Required failures exit 1; optional items are warnings, never failures.
- **Speech-rate QA gate.** `qa.py` flags narration outside ~1.5–5.5
  words/sec as a non-blocking warning (target 2–4), so robotic or rushed
  reads are surfaced without blocking the pipeline.
- **Shorts loop ending + cover frame (`src/video.py`).** `loop_ending`
  fades the actual first frame back in over the last 0.4s so the YouTube
  auto-replay reads as one intentional loop (duration and audio untouched).
  `cover_frame` extracts a clean early-frame JPEG beside each video for
  the Shorts shelf / custom thumbnail. Both best-effort, never fail a render.
- **Engagement drafts (`src/engage.py`).** After a run, writes human-reviewed
  end-screen plans (exact last-20s window) plus community-post and
  pinned-comment drafts built from the script's own verified content
  (`data/engagement_drafts.json` + `.md`). DRAFTS ONLY — YouTube has no
  public API for end screens/community posts, so nothing is auto-posted;
  you paste them in Studio. No LLM, no invented claims.
- **State backup/restore + quota tracking (`src/ops.py`).** `auto_backup`
  snapshots the pipeline's memory (niche lock, topic history, cache, upload
  feedback, ...) to `data/backups/*.tar.gz` before each run, keeping
  `backup_keep` archives. `faceless ops restore` extracts only allowlisted
  state files (no path traversal). Every counted YouTube/stock API call
  increments a daily counter; `quota_status` warns at 80% of the daily
  budget so a run degrades to fallback visuals instead of dying on a 403.

### Tests
- 62 new tests (`tests/test_tier23.py`): similarity dedupe + precision,
  language voice/metadata, learned publish hour bounds, doctor readiness,
  ops backup/restore/quota/prune, engagement drafts, speech-rate gate,
  Tier 2/3 config validation, upload language wiring, and the loop-ending
  / cover-frame render. Suite now 143 tests, green under stdlib and
  Pillow/PyYAML; ruff clean.

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
