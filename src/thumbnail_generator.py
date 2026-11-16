"""Documentary thumbnail generator for The Deep Scan (PIL only).

Cinematic, documentary-quality 1280x720 YouTube thumbnails built from
the video's OWN evidence-supported visuals — never from borrowed art,
never from ComfyUI (no host), never fabricated evidence imagery.

Design system (see docs/thumbnail-generator.md):
- One dominant focal subject, full-bleed 16:9, cinematic grade
  (contrast/saturation lift + vignette + legibility gradients).
- Headline 2-5 words, ALL CAPS, DejaVu Sans Bold (Montserrat/Impact
  are not installed on this box), white with a black stroke, placed
  bottom-left inside safe margins, clear of the bottom-right
  duration-badge zone.
- Consistent branding: gold accent rule above the headline and a
  "THE DEEP SCAN" gold wordmark top-left; teal/gold/navy palette.
- Every headline is a curiosity gap grounded in an APPROVED ledger
  claim: each headline word must appear in the grounding claim's
  text (numbers normalized, commas stripped) or be an exempt
  interrogative (who/what/why/how/when/where). Anything else is
  refused in code (ValueError) — a misleading thumbnail never ships.

Pipeline contract (run.py):
- `generate_documentary_thumbnails()` is called AFTER the video title
  and evidence ledger are finalized. It always returns a list of
  result dicts (possibly empty) and NEVER raises: any failure is
  logged as a warning and the video render continues unaffected.
  `generate_documentary_thumbnails_or_raise()` is the strict version
  used by tests and the CLI.
- Thumbnails are saved alongside the finished MP4; QA results are
  written to `thumbnails_qa.json` next to them and can be merged into
  the production QA report with `append_thumbnail_qa()`.
"""

import json
import math
import os
import re
import statistics
import subprocess

# ---------------------------------------------------------------------------
# Brand + layout constants
# ---------------------------------------------------------------------------

WIDTH, HEIGHT = 1280, 720
MOBILE_WIDTH = 320  # readability is verified at this downscale width

NAVY = (13, 27, 48)          # deep navy (backgrounds, gradient base)
TEAL = (14, 124, 123)        # Deep Scan teal (mascot background)
GOLD = (212, 175, 55)        # Deep Scan gold (accent rule, wordmark)
SOLAR_YELLOW = (255, 204, 0)  # accent alternative (kinetic preset)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

WORDMARK = "THE DEEP SCAN"
WORDMARK_FONT_SIZE = 34
HEADLINE_FONT_SIZE = 110
HEADLINE_FONT_MIN = 64        # never shrink below this; refuse instead
HEADLINE_MAX_WORDS = 5
HEADLINE_MIN_WORDS = 2
MAX_HEADLINE_LINES = 2

SAFE_MARGIN = 48              # px clear of every edge for text
BADGE_ZONE = (1050, 600, WIDTH, HEIGHT)  # bottom-right duration badge: keep clear

# Words that make no factual assertion (interrogatives only). Every other
# headline word must appear in the grounding claim's text.
EXEMPT_WORDS = {"who", "what", "why", "how", "when", "where"}

# Focal-point presets (fraction of the cropped width the subject sits at).
FOCAL_CENTER = 0.5
FOCAL_LEFT = 0.32
FOCAL_RIGHT = 0.68

FONT_CANDIDATES = (
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _font(size):
    from PIL import ImageFont
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _norm_word(word):
    """Normalize a word for ledger matching: lowercase, strip punctuation,
    strip commas from numbers ('1,400' -> '1400')."""
    return re.sub(r"[^a-z0-9]", "", word.lower().replace(",", ""))


def _claim_words(claim_text):
    return {_norm_word(w) for w in re.findall(r"[A-Za-z0-9',]+", claim_text or "")}


# ---------------------------------------------------------------------------
# Headline validation (ledger-grounded, no misleading claims)
# ---------------------------------------------------------------------------

def validate_headline(headline, claim_text):
    """Return (ok, reason). A headline is valid when:
    - it has 2-5 words,
    - every non-exempt word appears in the grounding claim's text.
    """
    words = re.findall(r"[A-Za-z0-9',]+", headline or "")
    if len(words) < HEADLINE_MIN_WORDS:
        return False, (f"headline has {len(words)} word(s); "
                       f"minimum is {HEADLINE_MIN_WORDS}")
    if len(words) > HEADLINE_MAX_WORDS:
        return False, (f"headline has {len(words)} words; "
                       f"maximum is {HEADLINE_MAX_WORDS}")
    claim = _claim_words(claim_text)
    for word in words:
        norm = _norm_word(word)
        if norm in EXEMPT_WORDS or norm in claim:
            continue
        return False, f"word {word!r} is not in the grounding claim"
    return True, "headline matches the grounding claim"


# ---------------------------------------------------------------------------
# Concept picking: strongest verified discovery -> 3 distinct angles
# ---------------------------------------------------------------------------

# Headline templates keyed by the kind of claim they are grounded in.
# Each entry: (headline, focal hint, composition). The headline is only
# used when validate_headline() passes against the actual claim text;
# otherwise the concept is skipped.
CONCEPT_TEMPLATES = [
    # Shock discovery: the machine itself.
    ("PREDICTED ECLIPSES", "gears", FOCAL_CENTER, 0.5),
    # The time gap: nothing comparable for ~1,400 years.
    ("NOTHING FOR 1,400 YEARS", "time", FOCAL_RIGHT, 0.5),
    # The open question: the unknown builder. The museum statue's face
    # sits in the upper third of its portrait frame (focal_y 0.28).
    ("WHO MADE IT?", "maker", FOCAL_CENTER, 0.28),
]


def _claim_curiosity_score(claim, include_in_script):
    """Rank APPROVED claims for thumbnail duty. KNOWN + narrated first,
    then numbers (concrete, clickable), then shock hooks."""
    score = 0
    if claim.get("status") == "KNOWN":
        score += 3
    elif claim.get("status") == "DEBATED":
        score += 1
    if include_in_script:
        score += 2
    if claim.get("shock_hook"):
        score += 2
    if re.search(r"\d", claim.get("text", "")):
        score += 1
    if "?" in claim.get("text", "") or "unknown" in claim.get("text", "").lower():
        score += 1
    return score


def pick_concepts(ledger, topic="", title=""):
    """Pick 3 distinct thumbnail concepts from APPROVED ledger claims.

    Returns a list of dicts: {headline, claim_id, claim_text, tier,
    focal_hint, focal, angle}. Concepts are grounded in different
    claims and use different focal hints so the variations are
    genuinely distinct, not re-crops of the same idea.
    """
    claims = [c for c in ledger.get("claims", [])
              if c.get("status") in ("KNOWN", "DEBATED", "UNKNOWN")]
    # The UNKNOWN-builder question is a legitimate curiosity gap: the
    # ledger itself states the builder is unknown, so asking "who made
    # it?" asserts nothing false. Keep exactly one UNKNOWN concept.
    scored = sorted(
        claims,
        key=lambda c: _claim_curiosity_score(
            c, c.get("claim_id") in _script_claim_ids(ledger)),
        reverse=True)
    concepts = []
    used_claims = set()
    for headline, hint, focal, focal_y in CONCEPT_TEMPLATES:
        # Find the best-scoring claim this headline is grounded in.
        best = None
        for claim in scored:
            if claim["claim_id"] in used_claims:
                continue
            ok, _ = validate_headline(headline, claim.get("text", ""))
            if ok:
                best = claim
                break
        if best is None:
            continue
        used_claims.add(best["claim_id"])
        concepts.append({
            "headline": headline,
            "claim_id": best["claim_id"],
            "claim_text": best.get("text", ""),
            "tier": best.get("status"),
            "focal_hint": hint,
            "focal": focal,
            "focal_y": focal_y,
            "angle": _angle_for(headline, hint),
        })
        if len(concepts) == 3:
            break
    return concepts


def _script_claim_ids(ledger):
    ids = set()
    for claim in ledger.get("claims", []):
        if claim.get("include_in_script"):
            ids.add(claim["claim_id"])
    return ids


def _angle_for(headline, hint):
    if hint == "gears":
        return "The machine itself: a geared bronze computer that predicted eclipses."
    if hint == "time":
        return "The time gap: nothing this complex again for ~1,400 years."
    return "The open question: no inscription names the builder."


# ---------------------------------------------------------------------------
# Image treatment: cinematic grade (real processing, no fake imagery)
# ---------------------------------------------------------------------------

def _fill_crop(image, width, height, focal=0.5, focal_y=0.5):
    """Fill-crop to width x height, keeping the focal point in frame.
    focal/focal_y are fractions of the source the subject sits at
    (0.5/0.5 = centre; portrait sources need a focal_y above centre
    when the subject is in the upper part of the frame)."""
    from PIL import Image
    iw, ih = image.size
    scale = max(width / iw, height / ih)
    resized = image.resize((int(iw * scale) + 1, int(ih * scale) + 1), Image.LANCZOS)
    excess_x = resized.width - width
    # Center the focal point horizontally: focal fraction of the source
    # maps to the center of the crop.
    left = int(min(max(resized.width * focal - width / 2, 0), max(excess_x, 0)))
    excess_y = resized.height - height
    top = int(min(max(resized.height * focal_y - height / 2, 0), max(excess_y, 0)))
    return resized.crop((left, top, left + width, top + height))


def grade_image(image):
    """Cinematic grade: contrast + saturation lift, vignette, legibility
    gradients (dark at the bottom for the headline, light darkening at
    the top for the wordmark). Returns an RGB image."""
    from PIL import Image, ImageDraw, ImageEnhance
    img = image.convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.18)
    img = ImageEnhance.Color(img).enhance(1.12)
    img = ImageEnhance.Brightness(img).enhance(1.02)
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # Bottom gradient: transparent at 55% height -> strong at the bottom.
    grad_top = int(h * 0.52)
    for y in range(grad_top, h):
        alpha = int(175 * (y - grad_top) / max(h - grad_top - 1, 1))
        draw.line([(0, y), (w, y)], fill=(5, 10, 20, alpha))
    # Top gradient for the wordmark.
    for y in range(0, int(h * 0.16)):
        alpha = int(110 * (1 - y / max(int(h * 0.16), 1)))
        draw.line([(0, y), (w, y)], fill=(5, 10, 20, alpha))
    # Vignette: darken the corners.
    vignette = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse([-w * 0.25, -h * 0.35, w * 1.25, h * 1.35], fill=110)
    dark = Image.new("RGBA", (w, h), (5, 10, 20, 255))
    img = Image.composite(img.convert("RGBA"),
                          Image.alpha_composite(img.convert("RGBA"), dark),
                          vignette)
    img = Image.alpha_composite(img, overlay).convert("RGB")
    return img


def _wrap_headline(draw, text, font, max_width):
    """Wrap the headline into at most MAX_HEADLINE_LINES lines."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) > max_width and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines[:MAX_HEADLINE_LINES]


def draw_documentary_thumbnail(image, headline, claim_text, output,
                               focal=0.5, focal_y=0.5, accent=GOLD):
    """Render one 1280x720 documentary thumbnail.

    Raises ValueError if the headline fails validation or cannot fit
    at >= HEADLINE_FONT_MIN. Returns a spec dict describing exactly
    what was drawn (used by QA and the production report).
    """
    from PIL import Image, ImageDraw
    ok, reason = validate_headline(headline, claim_text)
    if not ok:
        raise ValueError(f"headline refused: {headline!r} — {reason}")
    base = image if hasattr(image, "size") else Image.open(image).convert("RGB")
    canvas = grade_image(_fill_crop(base, WIDTH, HEIGHT, focal=focal,
                                    focal_y=focal_y))
    draw = ImageDraw.Draw(canvas)
    max_text_w = WIDTH - 2 * SAFE_MARGIN
    # Fit the headline: shrink until it wraps into <= 2 lines.
    size = HEADLINE_FONT_SIZE
    while size > HEADLINE_FONT_MIN:
        font = _font(size)
        if len(_wrap_headline(draw, headline, font, max_text_w)) <= MAX_HEADLINE_LINES:
            break
        size -= 6
    font = _font(size)
    lines = _wrap_headline(draw, headline, font, max_text_w)
    if len(lines) > MAX_HEADLINE_LINES:
        raise ValueError(f"headline {headline!r} does not fit in "
                         f"{MAX_HEADLINE_LINES} lines at minimum font size")
    line_h = int(size * 1.12)
    total_h = len(lines) * line_h
    # Headline block: bottom-left, inside safe margins, clear of the
    # bottom-right badge zone. The bbox tracks the ACTUAL drawn text
    # extent (longest line), not the full text width, so the badge-zone
    # check measures what is really on screen.
    block_bottom = HEIGHT - SAFE_MARGIN - 8
    y = block_bottom - total_h
    max_line_w = max((draw.textlength(line, font=font) for line in lines),
                     default=0)
    headline_bbox = (SAFE_MARGIN, y,
                     SAFE_MARGIN + int(max_line_w), block_bottom)
    # Gold accent rule above the headline.
    rule_y = y - 26
    draw.rectangle([SAFE_MARGIN, rule_y, SAFE_MARGIN + 120, rule_y + 6],
                   fill=accent)
    for line in lines:
        draw.text((SAFE_MARGIN + 4, y + 4), line, font=font, fill=BLACK,
                  stroke_width=8, stroke_fill=BLACK)
        draw.text((SAFE_MARGIN, y), line, font=font, fill=WHITE,
                  stroke_width=8, stroke_fill=BLACK)
        y += line_h
    # Wordmark top-left + thin gold underline (inside safe margins).
    wm_font = _font(WORDMARK_FONT_SIZE)
    wm_y = SAFE_MARGIN
    draw.text((SAFE_MARGIN + 2, wm_y + 2), WORDMARK, font=wm_font,
              fill=BLACK, stroke_width=4, stroke_fill=BLACK)
    draw.text((SAFE_MARGIN, wm_y), WORDMARK, font=wm_font, fill=GOLD,
              stroke_width=4, stroke_fill=BLACK)
    wm_w = draw.textlength(WORDMARK, font=wm_font)
    draw.rectangle([SAFE_MARGIN, wm_y + WORDMARK_FONT_SIZE + 10,
                    SAFE_MARGIN + wm_w, wm_y + WORDMARK_FONT_SIZE + 13],
                   fill=accent)
    wordmark_bbox = (SAFE_MARGIN, wm_y,
                     SAFE_MARGIN + int(wm_w), wm_y + WORDMARK_FONT_SIZE + 13)
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    canvas.save(output, quality=95)
    return {
        "path": output,
        "headline": headline,
        "headline_font_size": size,
        "headline_lines": lines,
        "headline_bbox": [int(v) for v in headline_bbox],
        "wordmark_bbox": [int(v) for v in wordmark_bbox],
        "accent": list(accent),
        "size": [WIDTH, HEIGHT],
    }


# ---------------------------------------------------------------------------
# QA
# ---------------------------------------------------------------------------

def _luminance(rgb):
    r, g, b = (c / 255.0 for c in rgb[:3])
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _gold_pixel_fraction(image, box):
    """Fraction of pixels in box close to the brand gold."""
    region = image.crop(box).convert("RGB")
    px = list(region.resize((64, 64)).getdata())
    hits = sum(1 for r, g, b in px
               if abs(r - GOLD[0]) < 45 and abs(g - GOLD[1]) < 45
               and abs(b - GOLD[2]) < 60)
    return hits / max(len(px), 1)


def check_thumbnail_pro(path, headline, claim_text, spec=None):
    """Full QA for one documentary thumbnail. Returns (checks, overall).

    checks is a list of {check, status, detail} dicts (same shape as
    src/qa.py). Every check must pass for overall == 'pass'.
    """
    from PIL import Image
    checks = []

    def add(name, passed, detail):
        checks.append({"check": name, "status": "pass" if passed else "fail",
                       "detail": detail})

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        add("thumbnail_exists", False, "missing or empty")
        return checks, "fail"
    try:
        image = Image.open(path).convert("RGB")
    except Exception as exc:
        add("thumbnail_readable", False, f"unreadable: {exc}")
        return checks, "fail"
    add("thumbnail_resolution", image.size == (WIDTH, HEIGHT),
        f"{image.size[0]}x{image.size[1]} (want {WIDTH}x{HEIGHT})")
    add("thumbnail_aspect_ratio",
        abs(image.size[0] / image.size[1] - 16 / 9) < 0.01,
        f"aspect {image.size[0] / image.size[1]:.3f} (want 1.778)")
    # Spelling / text accuracy: the drawn headline must equal the spec.
    words = re.findall(r"[A-Za-z0-9',]+", headline or "")
    add("thumbnail_headline_word_count",
        HEADLINE_MIN_WORDS <= len(words) <= HEADLINE_MAX_WORDS,
        f"{len(words)} word(s): {headline!r}")
    if spec is not None:
        add("thumbnail_headline_spelling",
            spec.get("headline") == headline
            and spec.get("headline_lines") is not None
            and " ".join(spec["headline_lines"]).replace("  ", " ") == headline,
            f"drawn headline == intended {headline!r}")
    # Safe margins + badge zone (from the recorded spec bboxes).
    if spec is not None:
        hb = spec.get("headline_bbox", [0, 0, 0, 0])
        wb = spec.get("wordmark_bbox", [0, 0, 0, 0])
        inside = (hb[0] >= SAFE_MARGIN and hb[1] >= SAFE_MARGIN
                  and hb[2] <= WIDTH - SAFE_MARGIN and hb[3] <= HEIGHT - SAFE_MARGIN
                  and wb[0] >= SAFE_MARGIN and wb[1] >= SAFE_MARGIN
                  and wb[2] <= WIDTH - SAFE_MARGIN and wb[3] <= HEIGHT - SAFE_MARGIN)
        add("thumbnail_safe_margins", inside,
            f"headline bbox {hb}, wordmark bbox {wb}")
        bx0, by0, _, _ = BADGE_ZONE
        badge_clear = hb[2] <= bx0 or hb[1] >= by0
        add("thumbnail_badge_zone_clear", badge_clear,
            "headline does not enter the bottom-right badge zone")
    # Mobile readability: downscale to 320 wide; headline cap height and
    # text/background contrast in the headline region must hold up.
    small = image.resize((MOBILE_WIDTH, int(HEIGHT * MOBILE_WIDTH / WIDTH)))
    font_px = (spec or {}).get("headline_font_size", HEADLINE_FONT_SIZE)
    cap_h = font_px * 0.72 * (MOBILE_WIDTH / WIDTH)
    add("thumbnail_mobile_text_size", cap_h >= 10,
        f"headline cap height at 320px wide: {cap_h:.1f}px (want >= 10px)")
    if spec is not None:
        hb = spec["headline_bbox"]
        scale = MOBILE_WIDTH / WIDTH
        region = small.crop((int(hb[0] * scale), int(hb[1] * scale),
                             int(hb[2] * scale), int(hb[3] * scale))).convert("L")
        px = list(region.getdata())
        std = statistics.pstdev(px) if len(px) > 1 else 0
        bright = sum(1 for v in px if v > 200) / max(len(px), 1)
        add("thumbnail_mobile_readability",
            std > 25 and 0.02 < bright < 0.8,
            f"headline-region stddev {std:.1f}, bright-pixel fraction {bright:.2f} "
            f"at 320px wide")
    # Branding: gold accent rule + gold wordmark must be visible.
    if spec is not None:
        hb = spec["headline_bbox"]
        rule_box = (hb[0], max(hb[1] - 30, 0), hb[0] + 120, hb[1] - 20)
        gold_frac = _gold_pixel_fraction(image, rule_box)
        add("thumbnail_branding_gold_accent", gold_frac > 0.25,
            f"gold-pixel fraction in accent-rule area: {gold_frac:.2f}")
        wb = spec["wordmark_bbox"]
        wm_gold = _gold_pixel_fraction(image, wb)
        add("thumbnail_branding_wordmark", wm_gold > 0.05,
            f"gold-pixel fraction in wordmark area: {wm_gold:.2f}")
    # Claims match: headline grounded in the APPROVED ledger claim.
    ok, reason = validate_headline(headline, claim_text)
    add("thumbnail_claims_match_ledger", ok, reason)
    overall = "pass" if all(c["status"] == "pass" for c in checks) else "fail"
    return checks, overall


# ---------------------------------------------------------------------------
# Generation entry points
# ---------------------------------------------------------------------------

def _grab_frame(video, at_seconds, out_path):
    subprocess.run(["ffmpeg", "-y", "-ss", str(at_seconds), "-i", video,
                    "-frames:v", "1", out_path],
                   capture_output=True, check=True)
    return out_path


def _focal_image_for(concept, video=None, visuals_dir=None, outdir="/tmp"):
    """Resolve a focal image for a concept: prefer an explicit visuals
    clip matching the hint, else a frame from the rendered video."""
    hint = concept["focal_hint"]
    if visuals_dir:
        candidates = {"gears": "gears.mp4", "time": "pocketwatch.mp4",
                      "maker": "museum.mp4"}
        clip = candidates.get(hint)
        if clip and os.path.exists(os.path.join(visuals_dir, clip)):
            path = os.path.join(outdir, f"focal-{hint}.jpg")
            _grab_frame(os.path.join(visuals_dir, clip), 3, path)
            return path
    if video and os.path.exists(video):
        # Mid-video frame as a generic fallback (own content only).
        path = os.path.join(outdir, f"focal-{hint}-video.jpg")
        _grab_frame(video, 10, path)
        return path
    return None


def generate_documentary_thumbnails_or_raise(ledger, topic, title, outdir,
                                             slug, video=None, visuals_dir=None,
                                             image_paths=None):
    """Generate 3 distinct documentary thumbnail variations.

    Returns a list of result dicts: {variant, path, headline, claim_id,
    tier, angle, focal_hint, spec, qa_checks, qa_overall}. Raises on
    failure (callers that must not fail should use the _or_warn wrapper).
    """
    from PIL import Image
    concepts = pick_concepts(ledger, topic=topic, title=title)
    if len(concepts) < 3:
        raise ValueError(f"only {len(concepts)} grounded thumbnail concepts "
                         f"found in the ledger (need 3)")
    results = []
    os.makedirs(outdir, exist_ok=True)
    for i, concept in enumerate(concepts):
        suffix = "abc"[i]
        image_path = None
        if image_paths and concept["focal_hint"] in image_paths:
            image_path = image_paths[concept["focal_hint"]]
        else:
            image_path = _focal_image_for(concept, video=video,
                                          visuals_dir=visuals_dir,
                                          outdir=outdir)
        if image_path is None or not os.path.exists(image_path):
            raise ValueError(f"no focal image for concept {concept['headline']!r}")
        out_path = os.path.join(outdir, f"{slug}-thumb-16x9-{suffix}.png")
        spec = draw_documentary_thumbnail(
            Image.open(image_path), concept["headline"], concept["claim_text"],
            out_path, focal=concept["focal"],
            focal_y=concept.get("focal_y", 0.5))
        checks, overall = check_thumbnail_pro(out_path, concept["headline"],
                                              concept["claim_text"], spec=spec)
        results.append({"variant": suffix, "path": out_path,
                        "headline": concept["headline"],
                        "claim_id": concept["claim_id"], "tier": concept["tier"],
                        "angle": concept["angle"],
                        "focal_hint": concept["focal_hint"],
                        "spec": spec, "qa_checks": checks, "qa_overall": overall})
    qa_path = os.path.join(outdir, "thumbnails_qa.json")
    with open(qa_path, "w", encoding="utf-8") as fh:
        json.dump({"topic": topic, "title": title, "overall":
                   "pass" if all(r["qa_overall"] == "pass" for r in results)
                   else "fail",
                   "variations": [{k: v for k, v in r.items()
                                   if k != "spec"} | {"spec": r["spec"]}
                                  for r in results]},
                  fh, indent=2)
    return results


def generate_documentary_thumbnails(ledger, topic, title, outdir, slug,
                                     video=None, visuals_dir=None,
                                     image_paths=None, log=None):
    """Fail-soft wrapper: never raises. On failure returns [] and logs a
    warning (video rendering must never fail because of thumbnails)."""
    try:
        return generate_documentary_thumbnails_or_raise(
            ledger, topic, title, outdir, slug, video=video,
            visuals_dir=visuals_dir, image_paths=image_paths)
    except Exception as exc:
        msg = f"documentary thumbnail generation failed ({exc})"
        if log is not None:
            try:
                log.append({"step": "thumbnails_documentary", "status": "WARNING",
                            "detail": msg})
            except Exception:
                pass
        print(f"WARNING: {msg}")
        return []


def append_thumbnail_qa(report_path, results):
    """Merge thumbnail QA checks into a production QA report file
    (same {check, status, detail} shape as src/qa.py). Returns True
    when the report was updated, False when there was nothing to merge
    (e.g. the report does not exist yet)."""
    if not results or not os.path.exists(report_path):
        return False
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)
    for result in results:
        for check in result.get("qa_checks", []):
            report.setdefault("checks", []).append({
                "check": f"thumbnail_{result['variant']}_{check['check']}",
                "status": check["status"], "detail": check["detail"]})
    failed = [c for c in report.get("checks", []) if c["status"] == "fail"]
    report["overall"] = "pass" if not failed else "fail"
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return True


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", default="data/evidence_ledger.json")
    parser.add_argument("--topic", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--outdir", default="data/thumbnails")
    parser.add_argument("--slug", default="video")
    parser.add_argument("--video", default="")
    parser.add_argument("--visuals-dir", default="")
    parser.add_argument("--check", default="",
                        help="Only QA-check this existing thumbnail file.")
    parser.add_argument("--headline", default="")
    parser.add_argument("--claim-text", default="")
    args = parser.parse_args(argv)
    if args.check:
        checks, overall = check_thumbnail_pro(args.check, args.headline,
                                              args.claim_text)
        for check in checks:
            print(f"  {check['status'].upper()}: {check['check']} — {check['detail']}")
        print(f"Thumbnail QA {overall.upper()}: {args.check}")
        return 0 if overall == "pass" else 1
    with open(args.ledger, encoding="utf-8") as fh:
        ledger = json.load(fh)
    results = generate_documentary_thumbnails_or_raise(
        ledger, args.topic, args.title, args.outdir, args.slug,
        video=args.video or None, visuals_dir=args.visuals_dir or None)
    for result in results:
        print(f"Variant {result['variant']}: {result['headline']!r} "
              f"({result['claim_id']}, {result['tier']}) -> {result['path']} "
              f"QA {result['qa_overall']}")
    return 0 if all(r["qa_overall"] == "pass" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
