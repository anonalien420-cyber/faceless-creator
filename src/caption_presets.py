"""Caption preset system for Deep Scan.

Three distinct subtitle designs for the same narration, rendered as ASS
(Advanced Substation Alpha) files in the same structural conventions as
``src/video.py`` ``make_ass`` (``[Script Info]`` / ``[V4+ Styles]`` /
``[Events]``, ``H:MM:SS.cc`` timings, ``{``/``}`` escaped in text).

This module is ADDITIVE: it does not modify the existing pipeline or the
current production subtitles. The current baseline style (kinetic
typography preset, DejaVu Sans Bold, UPPERCASE, 7-word even chunks) is
kept as ``BASELINE`` for comparison only.

Fonts
-----
Montserrat ExtraBold / Bold / Medium are bundled under ``assets/fonts/``
(static instances instantiated from the OFL variable font at
https://github.com/google/fonts/tree/main/ofl/montserrat, see
``assets/fonts/OFL.txt``). They are real TTFs with corrected name tables,
so fontconfig resolves ``"Montserrat ExtraBold"`` directly. If the bundled
files are missing at render time, each preset falls back to an installed
equivalent (Noto Sans ExtraBold, then DejaVu Sans Bold) and says so in
``resolve_font()``.

Rendering the bundled fonts: pass the font directory to the ASS filter,
e.g. ``-vf ass=captions.ass:fontsdir=assets/fonts`` — libass then finds
the bundled files even on a machine without Montserrat installed.

Design rules shared by all presets
-----------------------------------
- Maximum two lines per caption event.
- Text stays inside the platform safe areas: side margins >= 60px at
  1080px width, and the caption band sits above the 450px bottom UI
  buffer (MarginV 380-520 depending on preset).
- Events follow natural sentence segmentation (punctuation boundaries),
  never mid-phrase cuts except at the preview's 15s excerpt boundary.
- Emphasis is selective: only names, numbers and key terms are ever
  highlighted. Stopwords are never highlighted.
- Every preset is a plain ``CaptionPreset`` dataclass: all values are
  configurable, nothing is hardcoded in the render path.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(REPO_ROOT, "assets", "fonts")

# ASS colour is &HAABBGGRR (alpha, blue, green, red).
WHITE = "&H00FFFFFF"
BLACK = "&H00000000"
SOLAR_YELLOW = "&H00CCFF"      # #FFCC00 — Deep Scan brand accent
DEEP_TEAL = "&H00A6B814"        # #14B8A6 — Deep Scan teal accent
SHADOW_BLACK = "&H80000000"     # semi-transparent black (shadow colour)

# Words that may be highlighted. Anything not in this set is never given
# an emphasis colour, in any preset.
HIGHLIGHTABLE = {
    "bronze", "eclipses", "eclipse", "antikythera", "athens",
    "1900", "1901", "1902", "82", "30", "100", "1,400", "2,000",
    "machine", "mechanism", "gears", "gear", "builder", "unknown",
    "sponge", "wreck", "museum", "cathedrals", "medieval",
}

STOPWORDS = {
    "a", "an", "the", "in", "on", "of", "to", "and", "or", "for",
    "what", "that", "it", "is", "are", "was", "were", "its", "no",
    "about", "again", "until", "off", "now", "held", "at", "made",
    "who", "paid", "have", "we", "do", "you", "think", "does",
    "record", "actually", "support", "happened", "remains", "remains",
}


@dataclass
class CaptionPreset:
    """One complete caption design. Every value is configurable."""

    name: str
    slug: str
    description: str
    # Typography
    font_name: str            # ASS fontname (must resolve via fontconfig)
    font_file: str            # bundled TTF filename under assets/fonts/
    fallback_font_name: str   # used when the bundled file is missing
    fallback_font_file: str   # installed system file, for width measuring
    font_size: int            # points at 1080x1920 (scaled for other heights)
    bold: bool
    letter_spacing: float     # ASS Spacing field, px
    case: str                 # "upper" | "sentence"
    # Colour / outline / shadow
    primary_color: str        # ASS &HAABBGGRR
    highlight_color: str
    outline_color: str
    outline_width: int        # ASS Outline field, px
    shadow_depth: int         # ASS Shadow field, px (0 = none)
    shadow_color: str
    # Position (1080x1920 Shorts; MarginV is px above the bottom edge)
    alignment: int            # ASS alignment (2 = bottom-centre)
    margin_l: int
    margin_r: int
    margin_v: int
    # Behaviour
    max_words_per_event: int
    max_lines: int = 2
    animation: str = "none"   # "none" | "fade" | "karaoke"
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    # Highlighting: which words get the highlight colour. "karaoke" means
    # the spoken word lights up as it is said (Viral); "selective" means
    # only HIGHLIGHTABLE words are coloured (Documentary, Minimal).
    highlight_mode: str = "selective"
    highlight_words: frozenset = frozenset()


def _font_path(filename: str) -> str:
    return os.path.join(FONT_DIR, filename)


DOCUMENTARY = CaptionPreset(
    name="Modern Documentary",
    slug="documentary",
    description=(
        "Bold Montserrat ExtraBold, white text, dark outline and shadow, "
        "selective keyword highlighting in solar yellow. Sentence-based "
        "events, calm and authoritative — the documentary default."
    ),
    font_name="Montserrat ExtraBold",
    font_file="Montserrat-ExtraBold.ttf",
    fallback_font_name="Noto Sans ExtraBold",
    fallback_font_file="/usr/share/fonts/truetype/noto/NotoSans-ExtraBold.ttf",
    font_size=64,
    bold=False,  # ExtraBold file already carries the weight; no faux-bold
    letter_spacing=1.0,
    case="upper",
    primary_color=WHITE,
    highlight_color=SOLAR_YELLOW,
    outline_color=BLACK,
    outline_width=5,
    shadow_depth=3,
    shadow_color=SHADOW_BLACK,
    alignment=2,
    margin_l=60,
    margin_r=60,
    margin_v=400,
    max_words_per_event=6,
    animation="none",
    highlight_mode="selective",
    highlight_words=frozenset({
        "bronze", "eclipses", "antikythera", "1900", "1901",
    }),
)

VIRAL = CaptionPreset(
    name="Viral Short-Form",
    slug="viral",
    description=(
        "Larger Montserrat ExtraBold with karaoke word-by-word emphasis: "
        "each spoken word lights up in solar yellow as it is said, then "
        "settles back to white. Energetic but controlled — no flashing, "
        "no bouncing, one word at a time."
    ),
    font_name="Montserrat ExtraBold",
    font_file="Montserrat-ExtraBold.ttf",
    fallback_font_name="Noto Sans ExtraBold",
    fallback_font_file="/usr/share/fonts/truetype/noto/NotoSans-ExtraBold.ttf",
    font_size=80,
    bold=False,
    letter_spacing=1.5,
    case="upper",
    primary_color=WHITE,
    highlight_color=SOLAR_YELLOW,
    outline_color=BLACK,
    outline_width=6,
    shadow_depth=4,
    shadow_color=SHADOW_BLACK,
    alignment=2,
    margin_l=60,
    margin_r=60,
    margin_v=520,
    max_words_per_event=4,
    animation="karaoke",
    highlight_mode="karaoke",
    highlight_words=frozenset({
        "bronze", "eclipses", "antikythera", "1900", "1901",
    }),
)

MINIMAL = CaptionPreset(
    name="Cinematic Minimal",
    slug="minimal",
    description=(
        "Clean premium typography in Montserrat Medium, sentence case, "
        "gentle fade in/out, restrained emphasis — only one or two words "
        "per section take the gold accent. Quiet and confident."
    ),
    font_name="Montserrat Medium",
    font_file="Montserrat-Medium.ttf",
    fallback_font_name="Noto Sans",
    fallback_font_file="/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    font_size=54,
    bold=False,
    letter_spacing=2.0,
    case="sentence",
    primary_color=WHITE,
    highlight_color=SOLAR_YELLOW,
    outline_color=BLACK,
    outline_width=2,
    shadow_depth=2,
    shadow_color=SHADOW_BLACK,
    alignment=2,
    margin_l=80,
    margin_r=80,
    margin_v=380,
    max_words_per_event=8,
    animation="fade",
    fade_in_ms=180,
    fade_out_ms=220,
    highlight_mode="selective",
    highlight_words=frozenset({"eclipses", "antikythera"}),
)

PRESETS = {
    "documentary": DOCUMENTARY,
    "viral": VIRAL,
    "minimal": MINIMAL,
}

# The production baseline, kept for comparison. Not a new preset.
BASELINE_FONT = "DejaVu Sans"
BASELINE_SIZE = 72


def resolve_font(preset: CaptionPreset):
    """Return (ass_font_name, font_path_or_None, bundled: bool).

    Prefers the bundled Montserrat file; falls back to the installed
    equivalent and says so, so a render never silently swaps fonts.
    """
    bundled = _font_path(preset.font_file)
    if os.path.isfile(bundled):
        return preset.font_name, bundled, True
    return preset.fallback_font_name, preset.fallback_font_file, False


def measure_width(text: str, font_path: str, size: int) -> float:
    """Rendered width in px of ``text`` at ``size`` (Pillow metrics)."""
    from PIL import ImageFont

    try:
        return ImageFont.truetype(font_path, size).getlength(text)
    except Exception:
        return len(text) * size * 0.62


def fit_size(text: str, font_path: str, start_size: int, max_width: float) -> int:
    """Largest size <= ``start_size`` whose rendered width fits."""
    size = start_size
    while size > 8 and measure_width(text, font_path, size) > max_width:
        size -= 2
    return size


def _fmt(t: float) -> str:
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}.{int(round((t % 1) * 100)):02d}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")")


def _apply_case(word: str, case: str) -> str:
    return word.upper() if case == "upper" else word


def _chunk_sentence(words, max_words):
    """Split one sentence into balanced chunks of <= ``max_words``.

    Chunks are as equal as possible; a cut moves to just after a comma
    when one falls within two words of the balanced boundary, so cuts
    land on natural phrase breaks instead of mid-phrase.
    """
    if len(words) <= max_words:
        return [words]
    n = -(-len(words) // max_words)
    size = -(-len(words) // n)
    cut = size
    comma = [i for i, w in enumerate(words)
             if w["word"].rstrip().endswith(",") and abs(i + 1 - size) <= 2]
    if comma:
        # A comma cut must never push the chunk past max_words.
        cut = min(comma[0] + 1, max_words)
    return [words[:cut]] + _chunk_sentence(words[cut:], max_words)


def segment_words(words, preset: CaptionPreset):
    """Group timed words into caption events.

    ``words`` is a list of ``{"word", "start", "end"}`` dicts (word timings
    from transcription). Sentences are split first (``.``/``?``/``!``),
    then long sentences are chunked at natural phrase breaks. Returns a
    list of events; each event is a list of word dicts. Event times span
    first-word start to last-word end.
    """
    sentences, current = [], []
    for w in words:
        current.append(w)
        if w["word"].rstrip().endswith((".", "?", "!")):
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    events = []
    for sentence in sentences:
        events.extend(_chunk_sentence(sentence, preset.max_words_per_event))
    return events


def _split_line_words(words, preset: CaptionPreset):
    """Split one event's words into at most ``max_lines`` display lines.

    Breaks after a comma near the middle when one exists, else at the
    midpoint. Returns a list of word lists.
    """
    if len(words) <= 1:
        return [words]
    mid = len(words) // 2
    comma = [i for i, w in enumerate(words)
             if w["word"].rstrip().endswith(",")]
    # A comma cut must stay balanced: at least two words on each line,
    # and within two words of the midpoint. A comma at the very start
    # (e.g. an event beginning "1900, ...") would strand one word on
    # its own line, so it is not used as a break.
    near_mid = [i for i in comma
                if abs(i + 1 - mid) <= 2 and 2 <= i + 1 <= len(words) - 2]
    cut = (near_mid[0] + 1) if near_mid else mid
    lines = [words[:cut], words[cut:]]
    return [ln for ln in lines if ln]


def _highlight_word(word: str, preset: CaptionPreset, force: bool = False) -> str:
    """ASS-escaped word, coloured when it is in the preset's highlight set.

    ``force`` colours the word regardless of the highlight set (used for
    the currently-spoken word in karaoke mode).
    """
    clean = word.strip(".,?!;:").lower()
    text = _escape(_apply_case(word, preset.case))
    if force or (clean in preset.highlight_words and clean in HIGHLIGHTABLE):
        return (f"{{\\c{preset.highlight_color}&}}{text}"
                f"{{\\c{preset.primary_color}&}}")
    return text


def _event_text(event, preset: CaptionPreset, font_path: str, size: int,
                width: int, active_word=None):
    """Render one event's ASS text (line breaks, karaoke/fade).

    ``active_word``: when given (karaoke mode), that word is highlighted
    as the currently-spoken word; the full line stays on screen and only
    the highlight moves from word to word.
    """
    max_width = width - preset.margin_l - preset.margin_r
    line_words = _split_line_words(event, preset)
    plain_lines = [" ".join(_apply_case(w["word"], preset.case)
                            for w in ln) for ln in line_words]
    size = fit_size(max(plain_lines, key=len), font_path, size, max_width)
    rendered = []
    for ln in line_words:
        parts = [
            _highlight_word(w["word"], preset, force=(w is active_word))
            for w in ln
        ]
        rendered.append(" ".join(parts))
    text = "\\N".join(rendered)
    if preset.animation == "fade":
        text = f"{{\\fad({preset.fade_in_ms},{preset.fade_out_ms})}}{text}"
    return text, size


def build_ass(preset: CaptionPreset, words, path: str,
              width: int = 1080, height: int = 1920,
              duration: float | None = None) -> str:
    """Write an ASS caption file for ``preset`` from timed ``words``.

    ``words``: list of ``{"word", "start", "end"}``. Events follow sentence
    segmentation; times come from the words themselves, so captions stay
    in sync with the spoken narration. When ``duration`` is given, words
    starting at or after it are dropped and event ends are clamped to it,
    so no caption outlives the clip. Returns the written path.
    """
    font_name, font_path, _bundled = resolve_font(preset)
    # Scale the point size if the frame is not 1080 wide.
    size = int(round(preset.font_size * width / 1080))
    if duration is not None:
        words = [dict(w, end=min(w["end"], duration))
                 for w in words if w["start"] < duration]
    events = segment_words(words, preset)
    # Karaoke mode: one event per word, all showing the same two-line
    # layout, with only the highlight moving. This is deliberate: the
    # ASS \k karaoke tag does NOT render in this environment's libass
    # (verified 2026-11-16 with a minimal {\k100} test — all words
    # stayed white), so per-word events are how the word-by-word
    # highlight is actually produced. Word timings within a sentence
    # are contiguous, so the line never flickers off between words.
    timed = []
    for event in events:
        if preset.animation == "karaoke":
            for w in event:
                timed.append((w["start"], w["end"], event, w))
        else:
            timed.append((event[0]["start"], event[-1]["end"], event, None))
    # Two passes: first find the smallest size that fits every line
    # (an event that needs shrinking pulls the whole file down, so the
    # look stays consistent and no line ever overflows the safe width),
    # then render all events at that size.
    sized = []
    for event in events:
        _text, needed = _event_text(event, preset, font_path, size, width)
        sized.append(needed)
    size = min(sized) if sized else size
    # SecondaryColour is the karaoke highlight colour.
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: {preset.name},{font_name},{size},{preset.primary_color},"
        f"{preset.highlight_color},{preset.outline_color},"
        f"{preset.shadow_color},{-1 if preset.bold else 0},0,0,0,100,100,"
        f"{preset.letter_spacing:.1f},0,1,{preset.outline_width},"
        f"{preset.shadow_depth},{preset.alignment},{preset.margin_l},"
        f"{preset.margin_r},{preset.margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text",
    ]
    for start, end, event, active in timed:
        text, _used_size = _event_text(
            event, preset, font_path, size, width, active_word=active)
        lines.append(
            f"Dialogue: 0,{_fmt(start)},{_fmt(end)},{preset.name},,0,0,0,,{text}"
        )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def validate_preset(preset: CaptionPreset, width: int = 1080,
                    height: int = 1920):
    """Return a list of problems with ``preset`` (empty = valid)."""
    problems = []
    if not preset.font_name:
        problems.append("missing font_name")
    if preset.font_size < 24 or preset.font_size > 120:
        problems.append(f"font_size {preset.font_size} outside 24-120")
    if preset.max_lines != 2:
        problems.append(f"max_lines is {preset.max_lines}, must be 2")
    if preset.max_words_per_event < 1:
        problems.append("max_words_per_event < 1")
    if preset.margin_l < 40 or preset.margin_r < 40:
        problems.append("side margins below 40px")
    if preset.margin_v < 300 or preset.margin_v > 700:
        problems.append(f"margin_v {preset.margin_v} outside safe band 300-700")
    if preset.outline_width < 0 or preset.outline_width > 12:
        problems.append(f"outline_width {preset.outline_width} outside 0-12")
    if preset.animation not in ("none", "fade", "karaoke"):
        problems.append(f"unknown animation {preset.animation!r}")
    if preset.highlight_mode not in ("selective", "karaoke"):
        problems.append(f"unknown highlight_mode {preset.highlight_mode!r}")
    bad = {w for w in preset.highlight_words if w in STOPWORDS}
    if bad:
        problems.append(f"stopwords highlighted: {sorted(bad)}")
    unknown = {w for w in preset.highlight_words if w not in HIGHLIGHTABLE}
    if unknown:
        problems.append(f"highlight words not in allowed set: {sorted(unknown)}")
    _name, path, bundled = resolve_font(preset)
    if bundled and not os.path.isfile(path):
        problems.append(f"bundled font missing: {path}")
    if height - preset.margin_v < 300:
        problems.append("caption band too close to the bottom edge")
    return problems
