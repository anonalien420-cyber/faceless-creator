# Faceless YouTube Creator

A niche-configurable, $0-budget pipeline that finds what's in demand,
writes original scripts, narrates them, adds a royalty-free music bed,
renders a vertical HD video, and — only when you explicitly enable it —
uploads it as unlisted (draft-like) or scheduled for a peak window.

**No guarantee of fame or virality.** Automation saves production time.
Audience growth depends on topic choice, quality, consistency, and luck,
and no tool can promise it. Anyone selling that promise is overselling.
Peak times help timing; they do not guarantee popularity.

## What is free vs. what needs a key

| Source / step | Free? | Needs a key/token? |
|---|---|---|
| Trend comparison — YouTube | Manual input only | YouTube Data API key (`YT_API_KEY`) for automated search/mostPopular + real view counts |
| Trend comparison — Reddit | Yes, public subreddit JSON, no key | No — just name `reddit_subreddits` in `config.yaml` |
| Trend comparison — TikTok | Manual paste only | TikTok Research API token (`TIKTOK_RESEARCH_TOKEN`, requires approved access) for automated queries. No scraping — scraping TikTok breaks its terms and is not implemented. |
| Trend comparison — Facebook | Manual paste only | Graph API token (`FACEBOOK_GRAPH_TOKEN`); generic public video search is not available — Graph search is restricted to Pages you manage, so manual paste is the realistic route. |
| Trend comparison — Google | Yes, daily Trends RSS feed | No — `pytrends` (optional) gives richer interest-over-time data; RSS works without it. Google data is demand/interest only, never video views. |
| Script generation | Yes, offline | No |
| Narration — Edge TTS (free tier) | Yes, free | No |
| Narration — Kokoro (local tier) | Yes, free, open-weight | No — install with `pip install kokoro` (+ `soundfile`); not in requirements.txt by default because it is heavy |
| Narration — ElevenLabs (paid tier) | No, paid | Yes — `ELEVENLABS_API_KEY`; never required, never default |
| Music bed — trending-style match | Yes, if you use free Mixkit/Pixabay tracks | No — a Pexels/Pixabay key is only needed for their APIs, not for downloading a track URL you already have rights to use |
| HD stock video | Yes, with a free API key | `PEXELS_API_KEY` or `PIXABAY_API_KEY` for `--fetch-stock`; otherwise paste stock video URLs into `stock_video_urls` |
| Video rendering (ffmpeg) | Yes | No (ffmpeg is free software) |
| YouTube upload | Yes, via the free Data API | Yes — OAuth client (`client_secrets.json`) from Google Cloud Console, upload scope only |

Never put keys or tokens in `config.yaml` or in git. Use environment
variables / GitHub Secrets. `token.json` and `client_secrets.json` are
gitignored.

## Quick start (local, no upload)

```bash
cd faceless-creator
pip install -r requirements.txt
# ffmpeg must also be installed: apt/brew install ffmpeg
# 1. Rank your niches (offline demo — no keys needed):
python -m src.run --list-niches
#    -> data/niche_ranking.json and data/niche_ranking.md
# 2. Trends for one niche (manual demo, offline):
python -m src.trends --manual-only --input data/trends_input.example.json
#    -> data/top5.json and data/compare.md (includes trending audio profile)
# 3. Scripts for the top 3:
python -m src.script --input data/top5.json
#    -> data/scripts.json (also works directly from the example file)
# 4. Full run for one niche (dry-run upload by default):
python -m src.run --niche "personal finance tips"
#    Without --niche it picks the top-ranked niche that has data.
```

The demo example file is clearly marked EXAMPLE — its titles and any
figures are placeholders, not real stats. Replace it with
`data/trends_input.json` containing videos you verified yourself, or
set `YT_API_KEY` for real YouTube data.

## Choosing a niche: ranking, not guessing

`config.yaml` has a `niches:` list (starting examples: personal finance
tips, tech explainers, fitness, cooking, gaming, true crime stories,
home organization, personal productivity — edit it to niches you can
make 30+ original videos about). Run:

```bash
python -m src.run --list-niches
```

`src/trends.py` runs the multi-source compare for EACH niche and writes
`data/niche_ranking.json` + `data/niche_ranking.md`: niches ranked 1..N
with top 2 topics per niche, source breakdown, a demand score, and a
plain-language "why it's ranked here" line.

Demand score = sum of the niche's top-5 candidate scores + 10 per
distinct source reporting demand. That is a comparison aid, not a true
cross-platform unit — a YouTube view, a Reddit upvote, and a Google
interest point are not interchangeable, and the ranking file says so.
A niche with no candidates scores 0 and is flagged "no data", which
means "not measured", not "unpopular". **Never invent niche demand
numbers** — scores come only from the real sources / manual inputs
already in the project, with null/unverified flags as before.

One niche runs per day: the top-ranked niche with data, or the niche
you name with `--niche` / the workflow_dispatch input. It never runs
every niche in one day — that would spam uploads and split your channel.

## Trending music: style-matched, never the copyrighted song

Flow: `trends.py` captures each trending video's audio signal when a
source or manual input actually provides it — `trending_audio`,
`audio_genre`, `audio_tempo_bpm`, `audio_mood` in `trends_input.json`
— and builds a trending audio profile from the top 5 (most common
genre + median tempo + dominant mood). It never claims a song is
trending without a source entry.

`music.py` then scores every track in `music_library` against that
profile (genre match, mood match, tempo closeness) and mixes the best
match under the narration. Example: if trending is fast upbeat pop,
it picks a fast upbeat royalty-free pop-style track, not a random slow
one. The match (profile → chosen track → why) is logged to
`data/run_log.json`.

**Copyright rule, enforced in code:** do NOT download or use the actual
trending songs from TikTok/YouTube — that draws Content ID claims and
takedowns. The match is style/tempo/mood-alikeness with a royalty-free
track only. If you hold a licence for a specific track, put it in
`licensed_track` with a `license_note`: it is used as-is and logged
with its licence, never presented as royalty-free. If a real (non-example)
library is configured but no track matches the wanted genre/tempo/mood,
`music.py` FAILS with a clear message naming the wanted profile,
instead of silently using an unrelated track. If no library is
configured at all, narration ships without a music bed and warns.

## Voices: tiers, and what sounds most human

| Tier | Voice | Cost | How human does it sound? |
|---|---|---|---|
| `free` (default) | Edge TTS neural (Christopher/Aria) + SSML prosody | Free | Closest free option: neural synthesis, not robotic concatenative TTS |
| `local` | Kokoro open-weight, if installed | Free, local | Often more natural than Edge TTS; falls back to Edge if not installed |
| `paid` | ElevenLabs (key required) | Paid | Usually the most natural of the three; never required, never default |

Set `narrator_tier`, `narrator_voice`, `narrator_speed`, and
`narrator_pause_ms` in `config.yaml`. The humanizing pass emphasizes
the hook sentence, adds natural pauses at commas/periods, and varies
rate/pitch — those three things (neural synthesis + prosody + pacing)
are why a voice sounds human instead of monotone. No AI voice is
indistinguishable from a human, and this project never claims one is.
Narration is verified after rendering: empty or silent audio fails
loudly instead of shipping a silent video. Paid tier without a key
also fails loudly rather than silently downgrading.

## HD pictures and video that look better

Flow in `video.py`, in order:
1. **HD stock VIDEO clips first** — Pexels/Pixabay video API with
   `--fetch-stock` (needs `PEXELS_API_KEY` / `PIXABAY_API_KEY`), or
   URLs in `stock_video_urls`. 1080p minimum.
2. **HD still images second** — 1920px+ wide, with Ken Burns motion,
   only when no video clips are available.
3. **Animated gradient fallback** — only when no visuals exist at all.

Rules: every visual is scaled to FILL 1080×1920 and cropped (aspect
preserved — no stretch, no black bars). Any asset whose largest side
is below `min_resolution` (default 1080) is REJECTED with a log line
and the next best asset is used — a 480p clip upscaled is not HD.
Clips crossfade between segments, each segment's length matches the
narration, and a subtle colour grade (contrast/saturation lift via
ffmpeg `eq`) finishes the footage. Captions are large, high-contrast,
white with a thick black outline, plus a clean title card and progress
bar. Output is 1080×1920, 30fps, H.264 at `video_bitrate` (default
10 Mbps, inside the 8–12 Mbps Shorts range).

## Daily cadence: 1 long-form video + 2 Shorts, every day

Config: `long_videos_per_day: 1`, `shorts_per_day: 2` (both overridable,
but do not raise the defaults without a reason — more than 1 long + 2
Shorts a day risks spam and a quality drop).

Why both formats:
- **Long-form is for depth and search** — 16:9, 1920×1080, 8–12 minutes
  (~1200–1800 words, with chapters/sections), from the day's #1 topic
  in depth. Long videos are where a topic can actually rank in search.
- **Shorts are for reach and traction** — 1080×1920, 30–60 seconds,
  from topics #2 and #3. Shorts are where new viewers discover you.

One daily run (`src/run.py`) does both: trends run once for the chosen
niche, the #1 topic becomes the long video, #2 and #3 become the
Shorts, and every output goes through the same narrator/music
pipeline, the same QA gate below, and its own peak-time schedule.
**Traction is not guaranteed** — cadence and quality help, but no
schedule promises views.

## Peak-time publishing: render in the morning, publish at peak

Daily flow, 1 long + 2 Shorts per day, one niche per run:
1. **Morning render** — the GitHub workflow runs at 12:00 UTC
   (06:00 CST / 07:00 CDT Chicago), so rendering finishes well before
   the peak windows.
2. **Peak publish** — the upload step uses `--publish-at-peak`:
   each video uploads as private with YouTube's `publishAt` set to
   its own next peak window (see `src/scheduler.py`), and YouTube
   publishes it at that time. Shorts and long-form have separate
   windows (below).
3. **Manual review by default** — without `--publish-at-peak`, an
   upload stays unlisted for you to review. Without `UPLOAD_ENABLED`,
   everything dry-runs and nothing is posted.

Defaults in `config.yaml` (`peak_windows`, `channel_timezone`):
- Shorts: weekdays 12:00–14:00 (midday) and 17:00–20:00 (evening),
  weekends 11:00–13:00 — the scheduler picks the first window still
  ahead, so a morning render lands the midday slot.
- Long-form: weekdays 17:00–20:00, weekends 11:00–13:00 (evening peak).
- Per-niche overrides win over format windows
  (e.g. `"cooking:weekday:18:00-21:00"`).
These are **general YouTube audience windows, NOT a guarantee of
popularity**, and they are overridable per niche once you have your
own analytics. Check your own windows with:

```bash
python -m src.scheduler --niche "cooking" --list
python -m src.scheduler --niche "cooking" --format short
python -m src.scheduler --niche "cooking" --format long
python -m src.upload --video data/videos/01-x.mp4 --title "X" --dry-run --publish-at-peak --niche "cooking" --format short
```

## QA gate: no upload on QA failure

`src/qa.py` runs on every rendered MP4 **before** upload, using
ffprobe/ffmpeg only: file exists and is non-empty; duration matches
narration (within 2s); audio stream present and not silent
(volumedetect); no black/silent stretches over 2s; resolution is
1080×1920 (Shorts) or 1920×1080 (long-form); frame rate 30fps;
captions file present and non-empty; first 3 seconds not black
(title card); audio not clipping badly.

Auto-fixes, logged in `data/run_log.json`: re-mux with a volume gain
if too quiet, re-mux with a cut if clipping, re-render with fallback
visuals if a clip is missing/low-res or the title card is black,
re-run captions if the caption file is empty. **One retry only: if a
fix fails, or any check still fails after it, the run FAILS LOUDLY and
uploads NOTHING** — a broken video must never go out. Per-run report:
`data/qa_report.json` (plus per-video `data/qa_report_<format>_<slug>.json`).

```bash
python -m src.qa --video data/videos_short/01-x.mp4 --narration data/audio_mixed_short/01-x.mp3 --script-text "..." --title "X"
```

## Weekly self-review: corrects itself, within safe bounds

`.github/workflows/weekly-review.yml` runs every Sunday (14:00 UTC,
plus manual dispatch). `src/review.py` looks over videos published in
the last 7 days and writes `data/weekly_review.md` +
`data/weekly_review.json`: what's popular (top performers + what they
share — niche, hook style, length, music profile, publish time),
what's not (bottom performers + likely cause, stated as a
**hypothesis, not a fact**), and concrete adjustments.

Performance comes from real sources only: the YouTube Data API when
OAuth is set (views, likes, comments; retention is NOT available from
the Data API and stays null), otherwise `data/video_stats.json` — a
file you paste from YouTube Studio
(see `data/video_stats.example.json` for the format, EXAMPLE only).
**Never invent performance numbers:** videos with no stats are listed
as "no data yet" and are not scored.

What it auto-changes (safe bounds only, applied to `config.yaml`,
logged, and reversible via `data/review_history.json` before/after):
- Niche ranking: +20 demand bonus for the winning niche next run.
- Hook style: `review_preferred_hook_style` = top performers' style.
- Length: `review_preferred_length_seconds` = top performers' median,
  clamped to 30–60s for Shorts.
- Music: `review_music_genre/tempo/mood` = top performers' profile
  (music.py overrides the trending profile with it).
- Peak window: `review_peak_shift_minutes` toward winning publish
  hours, clamped to ±60 minutes.

What it NEVER does: delete videos, change a video's privacy after
publishing, change channel settings, or spend money. Anything bigger
than the bounds above (dropping a niche, switching to long-form only,
paid promotion) goes into `weekly_review.md` as a recommendation for
you — never an auto-change. To undo a week's adjustments, restore the
`before` values from `data/review_history.json` into `config.yaml`.

## Thumbnails + titles/SEO

`src/thumbnail.py` generates thumbnails with no paid API and no
copied art: 1280×720 for longs, 1080×1920 cover frames for Shorts,
bold high-contrast design, max 3–4 huge words, bright accent colours,
strong outline/shadow, and a before/after contrast where the video
supports it. The visual is always the video's own HD visual or a
frame from its own rendered video — never another creator's
thumbnail or copyrighted art.

**Clickbait style, not clickbait lies — hard rule, enforced in code:**
the thumbnail must match something actually in the video. No fake
results, no fake money amounts, no person/object that isn't in the
content, no misleading shock claims. `validate_claim()` checks every
thumbnail text against the script: a `$X` amount must appear in the
script, a `#N` claim must refer to a real beat/section N, and other
content words must appear in the script or topic. A refused claim
falls back visibly to a truthful curiosity line (e.g. "Stop Doing
This"). Misleading thumbnails risk YouTube strikes and viewer
distrust, so the generator refuses rather than invents.

**Two variants per video** (different curiosity text + focal crop:
variant A centre crop/yellow accent, variant B side crop/red accent)
so you can A/B pick in the review queue. Both variants are logged to
`data/seo.json` and listed in `data/review_queue.md` with their QA
results. Thumbnail QA (exact size, not blank, not low-res) is checked
per variant; a failed variant is flagged in the queue.

`src/seo.py` writes `data/seo.json` per run: 3 original title options
per video (hook-driven, under 60 characters for longs, punchy for
Shorts), 1 recommended title, a description (hook + CTA + channel
promise; timestamped chapters are prepended for longs at upload
time), tags from the trending keywords + topic words, and a
pinned-comment question (paste/pin it yourself — the API upload does
not pin comments). Titles are original, never copied from trending
videos.

## Retention editing

Built into `src/video.py`'s render, not a separate pass:
- **First 3 seconds payoff:** title card + hook line on screen
  immediately, no dead air, no long intro.
- **Pattern interrupts:** the visual re-cuts at least every 25s in
  longs and every 8–12s in Shorts (here: every 10s), with a visual
  switch, alternating zoom-in/zoom-punch, a caption pop, and a short
  on-screen prompt at each boundary — never one static Ken Burns shot.
- **No long silent gaps:** cuts are driven by narration length, and
  the QA gate rejects silent stretches over 2s.
- **End with a clear CTA:** the last 3 seconds carry an end card —
  Shorts push to the same-day long video, longs tease the next episode.

## Series + funnel

Config: `series_name`, `series_enabled`, `niche_lock_days` (default
90). When series is enabled, every daily output carries the series
name and an episode number (`EP N`) in its title/description.
Episode numbers auto-increment in `data/series_state.json` **only
after a successful render + QA pass** — never before, never on a
failed run (same pattern as the Shorts state file).

Funnel, every day: Shorts end with a card and description line
pushing to the same-day long video on the same topic; longs end with
a next-episode teaser. The long video is the depth/search anchor,
the Shorts are the discovery on-ramp to it.

**Niche lock — stay in one niche for 90 days for subscriber growth,
even if another niche ranks higher on a given day.** The first run
records the chosen niche in `data/niche_lock.json`; later runs keep
it until 90 days pass, then re-rank and lock the new winner. This is
a recommendation lock, not a prison: `--niche` overrides it for a
single run (without rewriting the lock).

## Human review queue (safety net, NOT full auto-public)

Default upload flow is now: upload as **UNLISTED** + write
`data/review_queue.md` — one entry per video with title, both
thumbnail variants (A/B pick), script summary, SEO (titles, tags,
pinned-comment question), QA result, and scheduled peak time.
**Review the queue before the peak window.** With
`--publish-at-peak` the video is private + scheduled, so the queue
review happens before YouTube publishes it at peak — that is the
intended safety window.

`--auto-public` exists but is **OFF by default**, and the README
warns against casual use: full auto-public risks factual and taste
mistakes QA cannot catch. **QA catches technical mistakes only**
(blank video, silent audio, wrong resolution, missing captions,
clipping). It cannot tell whether a claim is wrong, a joke lands
badly, or a thumbnail's curiosity line overpromises — those need
human eyes in the review queue.

## Monetization + channel promise

Config: `channel_promise` — one line, "this channel is THE place for
X", used in every video description (leave the placeholder and
run.py skips it). Fill it in once you pick the niche lock: it tells
a new viewer in one line why to subscribe.

YouTube Partner Program thresholds (as of this writing — verify in
YouTube Studio, thresholds can change):
- **Long-form path:** 1,000 subscribers + 4,000 public watch hours in
  the last 12 months.
- **Shorts path:** 1,000 subscribers + 10 million public Shorts views
  in the last 90 days.
Honest note: trending topics + daily cadence + peak-time scheduling
improve discovery, but they do **not guarantee #1 rankings,
virality, or monetization**. Growth still depends on topic choice,
quality, consistency, and luck — the pipeline saves production time,
it does not promise an audience.

## Locked niche: history mysteries investigated with modern tech

Channel niche (locked 2026-11-03, `niche_lock_days: 90`): unsolved
history and mysteries from around the world, investigated with modern
tech — lost cities, events nobody can fully explain, and artifacts
that shouldn't exist, reconstructed and tested with today's tools.
That line is also the `channel_promise` in `config.yaml` and is used
in video descriptions. The other niches in the list are alternatives
only; the daily run stays on this niche unless `--niche` overrides a
single run. Trend keywords: unsolved history, lost cities, historical
mysteries, ancient artifacts, unexplained events, forensic history,
satellite archaeology, AI reconstruction. Reddit: r/history,
r/UnresolvedMysteries, r/AncientHistory, r/AskHistorians.

## History-mystery scripts: evidence, theories, unexplained

`src/script.py` auto-detects this style when the first niche mentions
history + mystery (override with `--style history_mystery` /
`--style general`). Every history-mystery script is structured as
**evidence first, then competing theories, then what is still
unexplained** — and it follows three hard rules:
- Never present a theory as proven fact. Theories are labelled as
  theories ("one theory says…", "researchers disagree…").
- Never invent historical "facts". The template's concrete claims are
  structural; every real date, name, or finding must be checked
  against a real source before publishing.
- Cite sources in the script notes field: each script carries a
  `notes` field with these rules and a `sources` field that must be
  filled with the real sources verified for that topic before
  publishing — the generator cites no invented source, and the
  placeholder must not ship.

## Historical accuracy

Content principle, in plain language: **everything must be
historically accurate and only what is known to be true. Viewers
should be interested but well informed, and videos must leave
enough mystery open that viewers can bring their own thoughts and
speculations.**

Three claim tiers, carried on every history-mystery script section:
- **KNOWN** — a verified, sourced fact. A KNOWN section may not
  ship without a real source in the script's `sources` field.
- **DEBATED** — genuine disagreement, with both sides named and
  neither presented as settled.
- **UNKNOWN** — genuinely unexplained, stated plainly, never filled
  in with a guess.
No invented dates, names, quotes, artifacts, or findings, ever. A
concrete claim without a real source is **dropped** from the
script and listed in `dropped_unverified` — never softened into a
guess. Drama comes from delivery (hook, pacing, visuals), never
from exaggerating a fact; if a fact is uncertain, the narration
and captions say so. Every video ends open — "What do you think
happened?" — with a pinned-comment question inviting viewer
theories.

QA enforces the shape, not the truth: `src/qa.py`'s accuracy
checklist verifies that sources are filled (not the placeholder),
that every section carries a tier, that no KNOWN section lacks
sources, that the ending asks an open question, that the shock
hook is KNOWN-tier with a filled source, and that every
description source has a valid-looking URL or an explicit
no-public-URL flag. Any failure
**fails the run loudly and blocks upload**, exactly like a
technical QA failure, and accuracy failures are not auto-fixed.
**What QA cannot do is verify that a source is true.** That is
the human reviewer's job: before the peak publish window, the
reviewer must check every source in `data/review_queue.md`
(title, script summary, QA result, scheduled peak time) against
the real record — and correct or pull any video whose sources do
not hold up. Viewer comments and theories are engagement, not
evidence: a commenter's theory must never be presented in a later
video as fact.

## Shock, honestly

History must be **interesting**: use material that shocks people
or keeps them wanting to know more — but shock comes only from
real scale, contrast, or a twist inside verified facts, never from
exaggeration, invented numbers, or misleading framing.

- **Verified shock hook:** every history video opens with a
  genuinely surprising but TRUE fact, labelled KNOWN, with its
  source in the script's `shock_hook` field. The generator cannot
  invent one: supply it per video via the candidate's `shock_fact`
  + `shock_source` fields (e.g. in `data/trends_input.json`), or
  fill `shock_hook` in the script JSON by hand. A shock claim
  without a source is dropped by `drop_unverified` and the QA gate
  then blocks the video — no shocking claim ships unsourced.
- **Curiosity loops:** each section ends with an open question
  that the next section answers, so viewers keep watching to
  close the loop. The loops themselves claim nothing, so they need
  no source — they point at the next section's evidence, theories,
  or unknowns.
- **Cliffhanger ending:** every video ends with the open viewer
  question ("What do you think happened?") AND a next-episode
  tease. The tease names a real next topic only if one is
  supplied (`next_topic`); otherwise it stays generic — a next
  topic is never invented.
- **Sources viewers can look up:** every history description
  carries a "Sources you can check" section (museums, universities,
  archives, peer-reviewed publications, reputable encyclopedias,
  official records) with each source's title and URL. A source with
  no public URL is listed as "no public URL — available on request
  / see review queue" and flagged — a URL is NEVER invented. QA
  checks that the shock hook is KNOWN-tier and sourced, and that
  every description source has a valid-looking URL or an explicit
  no-public-URL flag, and fails loudly otherwise. As with all
  accuracy checks, QA verifies the *shape* (a source exists, a URL
  looks valid); the human reviewer must still verify each source
  is real and actually supports the claim before publishing.

- Scripts are original: hook + 3 beats + CTA, generated from a topic.
  Never copy a source video's title, script, or wording.
- No copyrighted characters, clips, or music. Music must be
  royalty-free (Mixkit/Pixabay free tracks or your own recordings),
  or a track you hold a licence for (see `licensed_track`).
- Never present a paraphrase of someone else's script as original.
- Trend numbers are only reported when they come from an API or a
  figure you verified yourself. API-less/manual entries are flagged
  `manual/unverified` with `engagement: null`.

## Upload safety

- Default privacy is **unlisted**, never public, unless you pass
  `--public` / `--auto-public` to `src.upload`. `--auto-public` is OFF
  by default: QA catches technical mistakes only, so review
  `data/review_queue.md` before using it (see "Human review queue").
- Every run writes `data/review_queue.md` (title, thumbnails, script
  summary, SEO, QA result, scheduled peak time) — review it before
  the peak window when `--publish-at-peak` is on.
- `--publish-at-peak` uploads as private + `publishAt` (required by
  YouTube for scheduled publishing); it flips public at that time.
- `src.upload` refuses to upload unless `UPLOAD_ENABLED=true`.
- `src.run` defaults to `--dry-run` for uploads; pass `--upload` (and
  optionally `--publish-at-peak`) to actually post.
- The GitHub workflow runs daily at 12:00 UTC and on manual dispatch
  (niche + publish_at_peak inputs), but its upload only happens with
  `secrets.UPLOAD_ENABLED == 'true'`.
- Upload failures fail the run loudly (non-zero exit + `data/run_log.json`),
  never a silent green run.

## Project layout

```
config.yaml                  # niches, voices, music library, visuals, peak windows, series, channel promise
src/
  config.py                  # minimal YAML-subset loader (stdlib)
  trends.py                  # YouTube/Reddit/TikTok/Facebook/Google compare + niche ranking
  scheduler.py               # next peak window per niche/format (+ review shift)
  script.py                  # original Short + long-form scripts (hooks, chapters)
  narrate.py                 # voice tiers (Edge / Kokoro / ElevenLabs) + SSML prosody
  music.py                   # trending-style royalty-free music matching + mixing
  video.py                   # HD stock video/images, crossfades, captions, colour grade, pacing pass
  thumbnail.py               # clickbait-style, truth-checked thumbnails (2 variants/video)
  seo.py                     # original titles, description, tags, pinned comment
  qa.py                      # QA gate: ffprobe/ffmpeg checks + one-retry auto-fixes
  review.py                  # weekly self-review, safe-bounded auto-corrections
  upload.py                  # YouTube upload, unlisted default, --publish-at-peak, --auto-public (off)
  run.py                     # orchestrator: 1 long + 2 Shorts, QA gate, thumbnails, SEO, review queue
data/
  trends_input.example.json  # EXAMPLE demo input (not real stats)
  top5.json                  # generated: top 5 + top 2 per source + audio profile
  compare.md                 # generated: cross-source comparison table
  niche_ranking.json/md      # generated: niches ranked by demand
  scripts_long.json          # generated: long-form script (chapters)
  scripts_shorts.json        # generated: Shorts scripts
  scripts_history_demo.json  # demo: history-mystery Short + long showing
                             # KNOWN/DEBATED/UNKNOWN tiers; generic structural
                             # text only, no invented historical facts
  seo.json                   # generated: titles, descriptions, tags, thumbnails, pinned comment
  qa_report.json             # generated: QA pass/fail per video (+ per-video reports)
  review_queue.md            # generated: human review queue (review before peak window)
  niche_lock.json            # generated: locked niche + date (90-day recommendation lock)
  series_state.json          # generated: next episode number (only after successful render+QA)
  weekly_review.md/json      # generated: weekly self-review + adjustments
  review_history.json        # generated: review before/after values (reversibility)
  video_stats.example.json   # EXAMPLE manual stats format for review.py
  run_log.json               # generated: per-step log (incl. music match, voice/tier)
.github/workflows/daily.yml  # morning render (1 long + 2 Shorts), peak publish, upload opt-in only
.github/workflows/weekly-review.yml  # Sunday self-review, safe bounds only
```

## What was NOT verified here

- Actual YouTube upload (requires your OAuth client + consent; never
  tested in this build).
- Edge TTS / Kokoro narration over the network (requires internet +
  the packages at runtime; compile-checked only).
- Live Reddit/Google RSS collection (network-dependent; the offline
  `--manual-only` demo path is the verified one).
- TikTok Research API / Facebook Graph API (require approved tokens
  that were not available; both fall back to manual paste).
- Pexels/Pixabay stock video APIs and ElevenLabs (require keys that
  were not available; not tested live).
- Full end-to-end `src.run` render (needs narration audio + ffmpeg at
  runtime; `src.video` itself was compile-checked only).


---

## Deep Scan: evidence-led historical documentary production

The history-mystery path now uses a claim-level evidence ledger. It is intentionally
fail-closed: research discovery is not fact verification, and a generated script
cannot turn an unreviewed search result into a KNOWN fact.

### Research discovery

Run a scholarly search:

```bash
python -m src.research --query "Pompeii eruption archaeological evidence"
```

OpenAlex and Crossref are queried without paid API keys. Candidate records are
written to `data/research_sources.json` and appended to
`data/evidence_ledger.json` with `review_status: UNREVIEWED`. Metadata includes
title, URL/DOI, authors, publication, year, provider, notes, and a discovery
priority hint. Institutional domains and primary-source repositories should be
prioritized during human review. Search results are leads, not proof.

### Claim-level review

Start from the example:

```bash
cp data/evidence_ledger.example.json data/evidence_ledger.json
python -m src.evidence --ledger data/evidence_ledger.json --validate
```

Each claim must have a unique `claim_id`, exact claim text, a status
(`KNOWN`, `DEBATED`, or `UNKNOWN`), reviewer identity, and ISO-8601
`reviewed_at`. KNOWN and DEBATED claims must cite one or more ledger sources
whose `review_status` is `APPROVED`, with a title and valid URL. DEBATED
claims additionally require a neutral summary of the disagreement. UNKNOWN
claims still require human review, but must not be dressed up as established
facts. Research discovery never sets source approval or claim status.

A source is approved only after a person checks that the cited record exists
and actually supports the exact claim. Record the reasoning in its `notes`.
Do not mark a source APPROVED merely because it is returned by OpenAlex or
Crossref.

### Evidence-driven scripts and scene prompts

History-mystery script generation now calls `src.documentary` and refuses to
write a script unless the ledger validates and includes a reviewed KNOWN
claim explicitly marked `shock_hook: true`. Each script section carries claim
IDs and source IDs. The documentary package includes scene-by-scene image and
animation prompts with period, location, clothing, architecture, objects,
lighting, camera movement, and atmosphere fields. Missing historical details
are called out rather than guessed.

Generated visuals are labelled as interpretive AI reconstructions, never
authentic historical footage. The prompts are production metadata; this
repository does not yet call a generative image/video provider to render those
prompts automatically.

### QA and publication safety

Historical QA now validates the full evidence ledger and confirms that script
claim IDs exist in it. Missing reviews, unapproved sources, missing claim
links, and invalid source records block the video before upload. The existing
FFmpeg, narration, captions, thumbnail, SEO, and review-queue steps remain in
place. The review queue now includes claim IDs and scene prompts.

The daily GitHub workflow is render/review only. `src.upload` refuses public
or scheduled-public flags and requires both `UPLOAD_ENABLED=true` and
`HUMAN_REVIEW_APPROVED=true` for a manual unlisted upload. Final public
publication must be performed by a person in YouTube Studio after reviewing
the evidence and video. Do not add automatic public publishing back to CI.

### Tests

Run the test suite with:

```bash
python -m unittest discover -s tests -v
```

The tests cover scholarly metadata mapping, research discovery remaining
unapproved, evidence review requirements, source approval, claim-ID integrity,
documentary hook safeguards, and publishing restrictions.
