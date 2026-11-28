# Architecture

## Pipeline
```
trends -> script -> narrate -> music -> video -> QA -> (seo, thumbnail) -> upload
```
`src/run.py` orchestrates one niche per run: the #1 topic becomes the
long-form video (16:9), #2/#3 become Shorts (9:16). Every output passes
the same narrator/music pipeline and the same QA gate. A QA failure
aborts the run — a broken video never uploads.

## Modules
| Module | Responsibility |
| --- | --- |
| `config.py` | YAML config (PyYAML or stdlib fallback) + fail-fast validation |
| `trends.py` | Multi-source demand collection; velocity + recency scoring |
| `research.py` | Free Wikipedia/Wikidata facts + sources; optional LLM draft |
| `script.py` | Original Shorts/long scripts; history-mystery tiers; topic memory; hook variants |
| `narrate.py` | Voice tiers; word-timing sidecar for captions |
| `music.py` | Royalty-free matching; ducking + loudness mastering |
| `video.py` | ffmpeg render; karaoke captions; brand cards; scene B-roll; parallel renders |
| `qa.py` | Technical + accuracy gate; auto-fix + recheck |
| `thumbnail.py` | Truth-checked A/B thumbnails; saliency crop; brand template |
| `seo.py` | Titles, description, tags, pinned comment, chapters |
| `scheduler.py` | Per-format peak windows; staggered publish times |
| `upload.py` | YouTube upload (dry-run default); private + publishAt |
| `review.py` | Weekly self-review; safe-bounded config corrections |
| `analytics.py` | YouTube Analytics API retention (watch time) for the review loop |
| `similarity.py` | Smooth TF-IDF cosine topic dedupe (stdlib, offline) |
| `localize.py` | Language→voice map + optional metadata translation |
| `doctor.py` | `faceless doctor` readiness report (env/config/keys/data) |
| `ops.py` | State backup/restore + daily API quota tracking |
| `engage.py` | End-screen + community/pinned drafts (human-reviewed, never auto-posts) |
| `models.py` | Typed dataclasses (Script/Scene/VideoReport/Brand/Source) |
| `brand.py` | Colour conversion + ASS/drawtext styling helpers |
| `cache.py` | Content-hash skip cache + ffprobe memoization |
| `cli.py` | Unified `faceless` entry point |

## Data flow (key files in `data/`)
- `top5.json`, `scripts_long.json`, `scripts_shorts.json` — candidates/scripts
- `audio_<fmt>/`, `audio_mixed_<fmt>/` — narration + mastered mix
- `<audio>.timings.json` — word/sentence caption timings (carried through the mix)
- `videos_<fmt>/` — rendered MP4 + `.ass` captions
- `qa_report_*.json`, `qa_report.json` — per-video + combined QA
- `thumbnails.json`, `seo.json`, `review_queue.md` — packaging + human review
- `run_log.json`, `run_manifest.json` — step log + production metrics
- `cache.json`, `topic_history.json`, `niche_lock.json`, `series_state.json` — state
- `publish_hours.json` — learned best publish hour per niche (Tier 2, opt-in)
- `api_usage.json` — daily API quota counters (Tier 3)
- `backups/*.tar.gz` — pre-run state snapshots (Tier 3, `backup_keep` retained)
- `engagement_drafts.json` + `.md` — end-screen/community/pinned drafts (Tier 3)
- `videos_<fmt>/*.cover.jpg` — clean cover frames for the Shorts shelf (Tier 3)

## Engine features
- **In-process vs subprocess.** `run.py --in-process` calls each stage's
  `main()` directly (one process, no interpreter startups). The default
  spawns a subprocess per stage for isolation. Both log identically.
- **Parallelism.** `video.py` renders videos in a thread pool (ffmpeg
  releases the GIL) and downloads stock concurrently. `max_workers=0`
  auto-sizes to the CPU count, capped at 4.
- **Caching.** A content hash of script text + voice + visuals keys
  `cache.json`; a hit skips re-TTS/re-render. ffprobe results are memoized.
  This also makes re-runs resume cheaply after a failure.
- **Captions.** Word timings drive karaoke highlighting; the active word
  takes the brand accent. Captions sit above the Shorts-safe bottom zone.
- **Brand.** One `brand:` block drives cards, captions, watermark, and
  thumbnails so every output reads as one channel.

## Extending
New stages should accept a dict (or a `models` dataclass) and return one,
log via `run.log_step`, and fail loudly. Keep the $0 default: any paid or
network capability is opt-in and degrades gracefully when unavailable.
