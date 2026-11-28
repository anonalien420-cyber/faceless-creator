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

## Tier 2 — reach + learning (added in 1.3.0)
- [x] **Semantic topic dedupe** (`src/similarity.py`): smooth TF-IDF cosine
      skips paraphrases of recent topics, not just exact repeats. Stdlib,
      offline, precision-leaning (distinct entities are never merged).
- [x] **Multi-language reach** (`src/localize.py`): config `language` picks
      a free neural voice + tags upload audio/metadata language; optional
      `localization_tier: api` translates metadata (template default never
      machine-translates).
- [x] **Learned publish hour**: the weekly review learns the best
      views-weighted hour per niche; the scheduler exploits it only inside
      an existing window and only after enough samples (bandit-lite,
      safe-bounded — never invents windows).

## Tier 3 — quality + operations (added in 1.3.0)
- [x] **`faceless doctor`** (`src/doctor.py`): one readiness report for
      env/config/keys/data; required failures exit 1, optional items warn.
- [x] **Speech-rate QA gate**: non-blocking warning for narration outside
      ~1.5–5.5 words/sec (target 2–4).
- [x] **Shorts loop ending + cover frame** (`src/video.py`): first frame
      fades back in over the last 0.4s for a clean auto-replay; a cover
      JPEG is extracted beside each video. Best-effort, duration preserved.
- [x] **Engagement drafts** (`src/engage.py`): end-screen plans +
      community/pinned drafts from verified script content. DRAFTS ONLY —
      no public API for end screens/community posts, so nothing auto-posts.
- [x] **State backup/restore + quota tracking** (`src/ops.py`): pre-run
      state snapshots (allowlisted restore, no traversal) + daily API
      counters that warn at 80% and degrade to fallback visuals.

## Notes / deliberate scope decisions
- The subprocess log-merge remains for the default isolated path;
  `--in-process` avoids per-stage interpreter startups while sharing the
  same log/manifest.
- mypy runs advisory (the dict-heavy pipeline is incrementally typed);
  ruff lint is a hard gate.
- Optional YouTube thumbnail A/B API and segment-pre-render/concat for
  very long form are left as future opt-in enhancements; the current
  parallel render + caching already covers the daily cadence efficiently.
- **Engagement is drafts-only, human-reviewed.** End screens and community
  posts have no public YouTube API, and auto-replying to comments with an
  LLM is deliberately NOT done. `engage.py` prepares paste-ready drafts
  from verified script content; a human posts them in Studio.
- **Similarity is lexical, not embeddings.** True synonyms with no shared
  word ("built"/"construction") are not caught — an embedding model would
  catch them but would break the $0/offline/no-download default. The
  threshold is config-tunable.
- **Learning is safe-bounded.** The learned publish hour is exploited only
  inside an existing peak window and only after enough samples; it never
  invents windows or rewires the schedule on one lucky upload.
