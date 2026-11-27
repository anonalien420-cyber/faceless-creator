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
