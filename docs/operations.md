# Operations

## Daily run
```bash
faceless run                                   # locked niche, dry-run upload
faceless run --niche "personal finance"        # override the niche lock for one run
faceless run --in-process                      # one process, faster (no per-stage startup)
faceless run --publish-at-peak                 # private + publishAt next peak window
faceless run --upload                          # actually upload (needs UPLOAD_ENABLED=true)
```
Default cadence: 1 long-form + 2 Shorts per day. Override with
`--long-count` / `--short-count` (0 disables a format). Raising the
defaults risks spam and a quality drop.

## Scheduling
`scheduler.py` picks per-format peak windows in `channel_timezone`
(Shorts: midday + evening; long-form: evening). Two Shorts in one run are
staggered to distinct windows. `--publish-at-peak` uploads private with a
`publishAt` time; nothing is public unless `--auto-public` is passed.

## Human review (safety net)
Every run writes `data/review_queue.md`: title, both thumbnail variants,
script summary, SEO, QA result, scheduled peak, and (for history videos)
the claim tiers + sources to verify. **Review it before the peak window.**
QA catches technical mistakes only; factual/taste mistakes need human eyes.

## Weekly self-review
```bash
faceless review --stats data/video_stats.json
```
Learns from the channel's own last 7 days (manual Studio export, or the
YouTube Data API when OAuth is connected). Applies only safe-bounded
config corrections (niche demand bonus, hook style, length, music profile,
peak shift ≤60 min). Bigger changes are recommendations, never auto-applied.
The views-weighted hook-style winner feeds the next run's hook selection.

## Feedback loop + trust (Tier 1)
- **Retention analytics.** Set `analytics_enabled: true` and provide a token
  with the `youtube-analytics.readonly` scope. The weekly review then pulls
  average view duration / percentage from the Analytics API, so hook/length
  corrections are driven by watch time. Without it, manual/Data-API stats
  are used (no breakage).
- **Upload verification.** Real uploads poll YouTube until processing
  finishes and record the `video_id` + status to `data/upload_feedback.json`
  and the run manifest. A failed/rejected upload is never logged as
  published. Disable with `verify_upload: false`.
- **On-screen citations.** History videos show verified sources on screen
  (`show_citations: true`). Only real, non-placeholder sources are shown —
  verify them in the review queue before publishing.

## Reach + learning (Tier 2)
- **Semantic topic dedupe.** Topic memory skips paraphrases of recent
  topics, not just exact repeats (`topic_similarity_threshold`, default
  0.6; 1.0 = exact-only). Stdlib/offline; precision-leaning so a distinct
  story is never silently dropped.
- **Multi-language.** Set `language` (e.g. `es-MX`) to narrate in that
  language's free neural voice and tag the upload's audio/metadata
  language. `localization_tier: api` (needs `LLM_API_KEY`) additionally
  translates title/description into YouTube `localizations`; the default
  `template` tier never machine-translates. Review translated metadata.
- **Learned publish hour.** Set `publish_learning: true`. The weekly review
  writes the best views-weighted publish hour per niche to
  `data/publish_hours.json`; the scheduler uses it only inside an existing
  peak window and only after `publish_learning_min_samples` (default 5)
  scored videos. It never invents new windows.

## Quality + operations (Tier 3)
- **Readiness check.** Run `faceless doctor` before a first run or after an
  environment change. Required failures (ffmpeg/ffprobe, config) exit 1;
  optional deps/keys are warnings that only disable their own features.
- **Speech-rate gate.** QA warns (non-blocking) when narration is outside
  ~1.5–5.5 words/sec, surfacing robotic/rushed reads in the QA report.
- **Loop ending + cover frame.** Shorts fade the first frame back in over
  the last 0.4s for a clean auto-replay (`loop_ending`), and a cover JPEG
  is written beside each video (`cover_frame`). Both best-effort.
- **Engagement drafts.** After a run, `data/engagement_drafts.json` + `.md`
  hold end-screen plans and community/pinned-comment drafts. DRAFTS ONLY —
  review and paste them in YouTube Studio (no public API for those).
- **State backup/restore.** `auto_backup` snapshots state to
  `data/backups/*.tar.gz` before each run (`backup_keep` retained). Restore
  with `faceless ops restore --archive data/backups/<file>.tar.gz` (only
  allowlisted state files are extracted).
- **Quota tracking.** Counted YouTube/stock API calls increment
  `data/api_usage.json` (daily reset). `faceless ops quota --service youtube`
  shows usage; the pipeline warns at 80% of the daily budget and falls back
  to manual/gradient visuals rather than dying on a 403.

## Caching + resume
`cache.json` skips re-TTS/re-render when script + voice + visuals are
unchanged, so a re-run after a failure resumes cheaply. Disable with
`cache_enabled: false`. Delete `data/cache.json` to force a full rebuild.

## Metrics
`data/run_manifest.json` records per-run render time, QA pass rate, and
upload status — one glanceable production summary.

## Topic memory
`data/topic_history.json` records covered topics; the script stage skips
topics covered within `topic_memory_days` (default 30) so the channel does
not repeat itself. Disable with `topic_memory: false`.

## GitHub Actions
- `daily.yml` — the daily run (env-passed inputs, secrets → files).
- `weekly-review.yml` — the weekly self-review.
- `crosspost.yml` — optional cross-posting.
- `tests.yml` — ruff lint gate, advisory mypy, unit + render tests, coverage.

## Troubleshooting
- **No thumbnails:** install Pillow (`pip install -r requirements.txt`).
- **Gradient backgrounds:** set a stock API key or add stock URLs; without
  them the render uses an animated gradient (still original).
- **QA failed:** read `data/qa_report_*.json`; fix the render and re-run.
  Accuracy failures (history videos) are not auto-fixable — supply verified
  sources and a sourced shock hook.
