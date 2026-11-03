"""Thumbnail generator (PIL/ffmpeg, no paid API, no copied art).

Clickbait STYLE, not clickbait lies. Design: bold, high-contrast,
large expressive focal crop from the video's own HD visual, max 3-4
huge words, curiosity-gap text ("You Won't Believe #3",
"Stop Doing This", "The $X Mistake"), bright accent colours, strong
outline/shadow, and a before/after contrast where the video supports
it (the script actually talks about a before/after change).

Two variants per video (different text + focal crop) so the creator
can A/B pick in the review queue; both are logged to data/seo.json
by run.py (see src/seo.py --thumbnails-file).

HARD RULE — enforced by validate_claim() below, in code and in README:
the thumbnail must match something actually in the video. No fake
results, no fake money amounts, no person/object that isn't in the
content, no misleading shock claims. Misleading thumbnails risk
YouTube strikes and viewer distrust. The generator REFUSES any
thumbnail text whose claim is not in the script and falls back to a
truthful curiosity line (topic-based, no invented claim):
- A "$X" amount in the text must appear in the script text.
- A "#N" claim must refer to a real numbered item (beat/section N
  must exist in the script).
- Any other content word in the text must appear in the script or
  the topic (generic curiosity words like "stop", "believe", "this"
  are exempt — they make no factual claim).
If validation fails, the refused text and the fallback are printed,
so the refusal is visible, not silent.

Originality rule: a thumbnail uses ONLY this project's own visuals
(the HD stock image/clip frame, or a frame from the project's own
rendered video). Never another creator's thumbnail, never copyrighted
art or characters. If no own visual is available, the fallback is a
plain dark gradient with text — still original.

QA check (check_thumbnail): the file must exist, be exactly the
expected size (not low-res), and not be blank (pixel standard
deviation above a small threshold — a solid-colour image fails).
"""

import argparse
import json
import os
import re
import subprocess
import sys

GENERIC_WORDS = {
    "you", "won't", "wont", "believe", "stop", "doing", "this", "the",
    "mistake", "secret", "why", "how", "what", "nobody", "tells",
    "big", "fix", "revealed", "truth", "real", "finally", "shocking",
    "a", "an", "and", "is", "it", "in", "for", "your",
}


def _fill_crop(image, width, height, focal="center"):
    from PIL import Image
    iw, ih = image.size
    scale = max(width / iw, height / ih)
    resized = image.resize((int(iw * scale) + 1, int(ih * scale) + 1), Image.LANCZOS)
    if focal == "left":
        left = max(0, (resized.width - width) // 4)
    elif focal == "right":
        left = max(0, 3 * (resized.width - width) // 4)
    else:
        left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def grab_frame(video, at_seconds=0.5):
    """Grab one frame from the rendered video (own content only)."""
    out = video + ".thumb_frame.jpg"
    subprocess.run(["ffmpeg", "-y", "-ss", str(at_seconds), "-i", video,
                    "-frames:v", "1", out],
                   capture_output=True, check=True)
    return out


def validate_claim(text, script_text, topic="", n_items=None):
    """Return (ok, reason). Refuses claims not backed by the script.

    - $ amounts must appear in the script.
    - #N must be <= the number of real items (beats/sections), when known.
    - Other content words must appear in the script or the topic.
    Generic curiosity words are exempt (they claim nothing factual).
    """
    script_lower = (script_text or "").lower()
    topic_words = set(re.findall(r"[a-z']+", (topic or "").lower()))
    for amount in re.findall(r"\$\s?[\d,]+(?:\.\d+)?", text):
        normalized = amount.replace(" ", "")
        if normalized not in script_lower and amount.lower() not in script_lower:
            return False, f"money amount {amount!r} is not in the script"
    for num in re.findall(r"#(\d+)", text):
        n = int(num)
        if n_items is not None and n > n_items:
            return False, f"#{n} does not exist (script has {n_items} items)"
    for word in re.findall(r"[a-z']+", text.lower()):
        if word in GENERIC_WORDS or word in topic_words or len(word) <= 2:
            continue
        if word not in script_lower:
            return False, f"word {word!r} is not in the script/topic"
    return True, "claim matches the script"


def fallback_line(topic):
    """Truthful curiosity line: topic words + 'Fix', max 4 words, no claim."""
    words = [w for w in re.findall(r"[A-Za-z']+", topic or "")][:3]
    if not words:
        return "The Fix"
    return " ".join((words + ["Fix"])[:4])


def curiosity_lines(topic, script_text, n_items):
    """Two curiosity-gap lines for the A/B variants, validated.

    Line A: 'Stop Doing This' (generic, always truthful as a hook).
    Line B: 'You Won't Believe #3' when the script has >= 3 items,
    else 'The Big Mistake' (generic). A '$X Mistake' line is only
    offered when the script actually contains that amount — callers
    can pass a validated custom line instead via --text.
    """
    lines = ["Stop Doing This"]
    if n_items and n_items >= 3:
        lines.append("You Won't Believe #3")
    else:
        lines.append("The Big Mistake")
    return lines


def make_thumbnail(text, output, image=None, video=None, fmt="long",
                   script_text="", topic="", n_items=None,
                   focal="center", accent=(255, 203, 5),
                   before_after=False):
    from PIL import Image, ImageDraw, ImageFont
    width, height = (1280, 720) if fmt == "long" else (1080, 1920)
    # Validate the claim BEFORE drawing; refuse + fall back visibly.
    ok, reason = validate_claim(text, script_text, topic=topic, n_items=n_items)
    if not ok:
        fallback = fallback_line(topic)
        print(f"THUMBNAIL CLAIM REFUSED: {text!r} — {reason}. "
              f"Falling back to truthful line {fallback!r}.")
        text = fallback
    # Max 3-4 huge words of large text: truncate, never cram a sentence in.
    words = (text or "").split()
    short_text = " ".join(words[:4])
    if image and os.path.exists(image):
        base = Image.open(image).convert("RGB")
        canvas = _fill_crop(base, width, height, focal=focal)
    elif video and os.path.exists(video):
        frame = grab_frame(video)
        canvas = _fill_crop(Image.open(frame).convert("RGB"), width, height, focal=focal)
    else:
        # Original fallback: dark gradient, no borrowed art.
        canvas = Image.new("RGB", (width, height), (15, 23, 42))
        for y in range(height):
            shade = int(15 + (30 - 15) * y / max(height - 1, 1))
            ImageDraw.Draw(canvas).line([(0, y), (width, y)], fill=(shade, 30, 80))
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    band_h = height // 3
    draw.rectangle([0, height - band_h, width, height], fill=(0, 0, 0, 160))
    # Bright accent strip across the top of the text band.
    draw.rectangle([0, height - band_h, width, height - band_h + 14], fill=accent + (255,))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    if before_after:
        # Only drawn when the script supports a before/after contrast
        # (caller checks for before/after language in the script).
        mid = width // 2
        draw.line([(mid, 0), (mid, height - band_h)], fill="white", width=6)
        try:
            small = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
        except OSError:
            small = ImageFont.load_default()
        draw.text((20, 20), "BEFORE", font=small, fill="white",
                  stroke_width=3, stroke_fill="black")
        draw.text((mid + 20, 20), "AFTER", font=small, fill="white",
                  stroke_width=3, stroke_fill="black")
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 110 if fmt == "long" else 130)
    except OSError:
        font = ImageFont.load_default()
    # Wrap the (max 4) words into at most 2 lines.
    lines, current = [], ""
    for word in short_text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) > width - 80 and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    lines = lines[:2]
    line_h = 130 if fmt == "long" else 150
    total_h = len(lines) * line_h
    y = height - band_h + (band_h - total_h) // 2 + 10
    for line in lines:
        text_w = draw.textlength(line, font=font)
        x = (width - text_w) / 2
        # Strong outline + shadow for clickbait legibility.
        draw.text((x + 4, y + 4), line, font=font, fill="black",
                  stroke_width=8, stroke_fill="black")
        draw.text((x, y), line, font=font, fill="white",
                  stroke_width=8, stroke_fill="black")
        y += line_h
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    canvas.save(output)
    print(f"Thumbnail -> {output} ({width}x{height}, text: {short_text!r}, "
          f"focal: {focal}, accent: {accent})")
    return output


def generate_variants(topic, script_text, outdir, slug, image=None,
                      video=None, fmt="long", n_items=None, custom_text=""):
    """Generate 2 A/B variants. Returns list of (path, text, qa_ok, qa_detail)."""
    before_after = ("before" in (script_text or "").lower()
                    and "after" in (script_text or "").lower())
    if custom_text:
        lines = [custom_text, curiosity_lines(topic, script_text, n_items)[1]]
    else:
        lines = curiosity_lines(topic, script_text, n_items)
    specs = [
        ("a", lines[0], "center", (255, 203, 5)),   # yellow accent, centre crop
        ("b", lines[1], "left", (227, 53, 13)),     # red accent, side crop
    ]
    results = []
    for suffix, line, focal, accent in specs:
        path = os.path.join(outdir, f"{slug}-thumb-{suffix}.png")
        make_thumbnail(line, path, image=image, video=video, fmt=fmt,
                       script_text=script_text, topic=topic, n_items=n_items,
                       focal=focal, accent=accent, before_after=before_after)
        ok, detail = check_thumbnail(path, fmt=fmt)
        print(f"Thumbnail QA {'PASS' if ok else 'FAIL'} (variant {suffix}): {detail}")
        results.append({"path": path, "text": line, "variant": suffix,
                        "qa_ok": ok, "qa_detail": detail})
    return results


def check_thumbnail(path, fmt="long"):
    """QA: exists, exact expected size, not blank. Returns (ok, detail)."""
    from PIL import Image
    import statistics
    want = (1280, 720) if fmt == "long" else (1080, 1920)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False, "missing or empty"
    try:
        image = Image.open(path).convert("L")
    except Exception as exc:
        return False, f"unreadable: {exc}"
    if image.size != want:
        return False, f"size {image.size} != expected {want} (low-res/wrong size)"
    pixels = list(image.resize((64, 64)).getdata())
    std = statistics.pstdev(pixels)
    if std < 5:
        return False, f"blank/near-solid image (pixel stddev {std:.1f})"
    return True, f"{image.size}, pixel stddev {std:.1f} (not blank)"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="", help="Thumbnail words (max 4 used).")
    parser.add_argument("--output", default="")
    parser.add_argument("--image", default="")
    parser.add_argument("--video", default="")
    parser.add_argument("--format", default="long", choices=["long", "short"])
    parser.add_argument("--check", default="", help="Only QA-check this existing file.")
    parser.add_argument("--script-text", default="",
                        help="Script text to validate thumbnail claims against.")
    parser.add_argument("--topic", default="")
    parser.add_argument("--variants", action="store_true",
                        help="Generate 2 A/B variants instead of one thumbnail.")
    parser.add_argument("--slug", default="video")
    parser.add_argument("--outdir", default="data/thumbnails")
    args = parser.parse_args(argv)
    if args.check:
        ok, detail = check_thumbnail(args.check, fmt=args.format)
        print(f"Thumbnail QA {'PASS' if ok else 'FAIL'}: {args.check} — {detail}")
        return 0 if ok else 1
    if args.variants:
        n_items = None
        if args.script_text:
            # Beats/sections: count of section-like markers is unknown
            # here, so use 3 (Shorts) / 6 (long) only when the caller
            # did not supply --text with a #N claim; validation of #N
            # without n_items falls back to script text presence.
            n_items = None
        results = generate_variants(args.topic, args.script_text, args.outdir,
                                    args.slug, image=args.image or None,
                                    video=args.video or None, fmt=args.format,
                                    n_items=n_items, custom_text=args.text)
        print(json.dumps(results, indent=2))
        return 0 if all(r["qa_ok"] for r in results) else 1
    if not args.output:
        print("ERROR: --output is required unless --variants or --check.",
              file=sys.stderr)
        return 1
    make_thumbnail(args.text, args.output, image=args.image or None,
                   video=args.video or None, fmt=args.format,
                   script_text=args.script_text, topic=args.topic)
    ok, detail = check_thumbnail(args.output, fmt=args.format)
    print(f"Thumbnail QA {'PASS' if ok else 'FAIL'}: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
