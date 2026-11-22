# Deep Scan Documentary Thumbnail Generator

`src/thumbnail_generator.py` — cinematic 1280×720 YouTube thumbnails,
built from the video's OWN evidence-supported visuals. It extends the
existing `src/thumbnail.py` (which still makes the 2 clickbait-style
A/B variants); this module adds the documentary system on top of it.

## Design system

- **Format:** 1280×720, 16:9, high-quality PNG. One dominant focal
  subject, full-bleed, cinematic grade (contrast 1.18, colour 1.12,
  vignette, bottom gradient for text legibility, top gradient for the
  wordmark). Real image processing only — no fake imagery.
- **Headline:** 2–5 words, ALL CAPS, DejaVu Sans Bold (Montserrat /
  Impact are not installed on this box), white with a black stroke,
  bottom-left, auto-fit (shrinks from 110px to a 64px floor, max 2
  lines). Never smaller, never more lines.
- **Branding:** gold accent rule above the headline + "THE DEEP SCAN"
  gold wordmark top-left. Palette: deep navy `#0D1B30`, teal `#0E7C7B`,
  gold `#D4AF37`, solar yellow `#FFCC00`.
- **Safe margins:** 48px clear of every edge for text; the bottom-right
  duration-badge zone (x > 1050, y > 600) is kept clear.
- **Mobile readability:** verified at a 320px-wide downscale — headline
  cap height ≥ 10px and headline-region contrast must hold up.

## Curiosity gaps, honestly grounded

Each run produces **3 distinct variations** from different APPROVED
ledger claims:

| Variation | Headline | Grounded in | Angle |
|---|---|---|---|
| a | PREDICTED ECLIPSES | `antikythera_01` (KNOWN) | The machine itself |
| b | NOTHING FOR 1,400 YEARS | `antikythera_09` (KNOWN) | The time gap |
| c | WHO MADE IT? | `antikythera_10` (UNKNOWN) | The open question |

The headline rule is enforced in code (`validate_headline`): every
non-exempt word must appear in the grounding claim's text (numbers
normalized, commas stripped); only interrogatives (who/what/why/how/
when/where) are exempt because they assert nothing. A headline that
fails is refused with `ValueError` — a misleading thumbnail never
ships. The UNKNOWN-builder question is legitimate precisely because
the ledger states the builder is unknown.

Focal imagery comes only from the production's own real visuals
(Pexels stock clips used in the video, museum photos, or frames of
the rendered video itself). The `wreck.mp4` clip was deliberately
NOT used: it shows a modern plane wreck, not the Antikythera wreck,
and would mislead. ComfyUI is not used (no host).

## QA (`check_thumbnail_pro`)

Per variation, same `{check, status, detail}` shape as `src/qa.py`:
resolution, aspect ratio, headline word count, headline spelling
(drawn == intended), safe margins, badge-zone clearance, mobile text
size, mobile readability (downscaled contrast), branding (gold accent
+ wordmark visible), claims-match against the ledger. Results are
written to `thumbnails_qa.json` next to the MP4 and merged into the
production QA report with `append_thumbnail_qa()`.

## Pipeline integration

`run.py` calls `generate_documentary_thumbnails()` after the video
title and evidence ledger are finalized, saving variations alongside
the finished MP4. **Fail-soft:** the wrapper never raises — any
failure logs a WARNING and the video render / QA outcome continues
unaffected (proven by `test_fail_soft_wrapper_never_raises`).

CLI:

```
python -m src.thumbnail_generator --ledger data/evidence_ledger.json \
  --topic "The 2,000-Year-Old Object That Shouldn't Exist" \
  --title "A 2,000-Year-Old Machine That Predicted Eclipses" \
  --outdir productions/antikythera-short-2026-11-15 \
  --slug DeepScan-Antikythera-Short-2026-11-15
```

## First run (2026-11-15)

All three Antikythera variations QA **pass** (11 checks each):

- `DeepScan-Antikythera-Short-2026-11-15-thumb-16x9-a.png`
  (632,501 bytes) — gears close-up, PREDICTED ECLIPSES.
- `DeepScan-Antikythera-Short-2026-11-15-thumb-16x9-b.png`
  (607,270 bytes) — skeleton pocket watch, NOTHING FOR 1,400 YEARS.
- `DeepScan-Antikythera-Short-2026-11-15-thumb-16x9-c.png`
  (684,928 bytes) — museum statue face, WHO MADE IT?

One defect was caught by visual review and fixed: the first render of
variation C cropped a portrait statue photo to the beard (centred
vertical crop). Fixed with a `focal_y` parameter (face sits at 0.28
of the frame) plus a regression test
(`test_portrait_subject_in_upper_third_survives_crop`). Mobile
downscales (320px) were visually checked: all three headlines stay
readable. The existing 1080×1920 Short thumbnail was not touched.
