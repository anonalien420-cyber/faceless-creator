"""Caption treatments: an ADAPTER layer over ``src/caption_presets.py``.

Three treatments built on the existing presets — the presets module is
READ-ONLY and is never edited here. If ``caption_presets`` cannot be
imported (e.g. this file is copied out of the repo), a minimal built-in
definition is used instead and ``PRESETS_FALLBACK_USED`` is True, so a
render never silently proceeds on unknown typography.

Treatments
----------
* ``hook`` — largest type, first 3 seconds only. Strongest words
  highlighted, appears by 0.5 s.
* ``fact`` — an important fact grounded in one ledger claim id: keyword
  colour highlight + a subtle scale emphasis on the key word/number only.
* ``narration`` — ordinary narration: calm word-by-word / short-phrase
  captions, no bounce, no karaoke, no scale on every word.

Research grounding (findings supplied with this task)
-----------------------------------------------------
* Hook in the first 3 s; 50-60% of drop-off happens in the first 3 s;
  text on screen by 0.5 s, voice starting immediately, motion from frame 1.
* Captions in 1-4 word groups, word-synced, active-word highlight;
  captions add ~18% watch time; ~80% watch muted.
* Captions centred ~70-80% down a 1080x1920 frame, inside safe zones.
* Word-by-word animation must feel professionally edited — never make
  every word bounce; emphasis only on important words.

Rules enforced in code (not just in docs)
------------------------------------------
* Max two lines per event (``max_lines = 2`` on every treatment, and
  ``validate_ass_file`` re-checks the written file).
* Text inside mobile safe zones: side margins >= 60 px at 1080 px wide,
  caption band MarginV 380-576 px, i.e. the band sits ~70-80% down the
  1920 px frame and above the bottom UI buffer.
* Emphasis only on the allowed keyword set: names, numbers and key terms
  from the evidence ledger (see ``allowed_keywords``). A word outside
  the set can never be coloured or scaled, in any treatment.
* Scale emphasis is applied ONLY to highlighted words (never every
  word), and only in the ``hook`` and ``fact`` treatments. The
  ``narration`` treatment has no scale and no karaoke at all.
* ASS generation is deterministic: same words + treatment -> byte-identical
  file. No randomness, no wall-clock input, no network.

Word timings
------------
Timings come from the narration audio, not from the script text:
``get_word_timings`` decodes the audio to 16 kHz mono float32 PCM with
ffmpeg first and passes a numpy array to faster-whisper (faster-whisper's
``decode_audio`` is broken against the installed PyAV, so the file path
must never be handed to it directly). The caption TEXT always comes from
the script — ``align_script_to_timings`` maps whisper's heard words onto
the script's written words, so mishearings (``Antikithra``) and split
numbers (``2`` + ``,000``) never reach the screen. If faster-whisper is
unavailable, ``estimate_word_timings`` gives deterministic evenly-spaced
timings as a clearly-labelled fallback.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

try:
    from src import caption_presets as _presets
    from src.caption_presets import (
        HIGHLIGHTABLE,
        STOPWORDS,
        fit_size,
        measure_width,
        resolve_font,
    )
    PRESETS_FALLBACK_USED = False
except Exception:  # pragma: no cover - only when presets module is absent
    _presets = None
    PRESETS_FALLBACK_USED = True
    # Minimal built-in definition, mirroring the presets' public contract.
    HIGHLIGHTABLE = frozenset({
        "bronze", "eclipses", "eclipse", "antikythera", "athens",
        "1900", "1901", "1902", "82", "30", "100", "1,400", "2,000",
        "machine", "mechanism", "gears", "gear", "builder", "unknown",
        "sponge", "wreck", "museum", "cathedrals", "medieval",
    })
    STOPWORDS = frozenset({
        "a", "an", "the", "in", "on", "of", "to", "and", "or", "for",
        "what", "that", "it", "is", "are", "was", "were", "its", "no",
        "about", "again", "until", "off", "now", "held", "at", "made",
        "who", "paid", "have", "we", "do", "you", "think", "does",
    })

    def measure_width(text, font_path, size):  # type: ignore
        try:
            from PIL import ImageFont
            return ImageFont.truetype(font_path, size).getlength(text)
        except Exception:
            return len(text) * size * 0.62

    def fit_size(text, font_path, start_size, max_width):  # type: ignore
        size = start_size
        while size > 8 and measure_width(text, font_path, size) > max_width:
            size -= 2
        return size

    def resolve_font(preset):  # type: ignore
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets", "fonts", preset.font_file)
        if os.path.isfile(path):
            return preset.font_name, path, True
        return preset.fallback_font_name, preset.fallback_font_file, False


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(REPO_ROOT, "assets", "fonts")
TTS_VENV_PYTHON = os.path.expanduser("~/workspace/tts_venv/bin/python")

# Colours in ASS &HAABBGGRR, matching caption_presets.
WHITE = "&H00FFFFFF"
BLACK = "&H00000000"
SOLAR_YELLOW = "&H00CCFF"       # #FFCC00 — Deep Scan brand accent
SHADOW_BLACK = "&H80000000"

# Mobile safe zones for a 1080x1920 Short (research: band ~70-80% down).
SAFE_MARGIN_LR = 60             # px minimum side margin at 1080 wide
SAFE_MARGIN_V_MIN = 380         # px above bottom edge (band top ~80% down)
SAFE_MARGIN_V_MAX = 576         # px above bottom edge (band top ~70% down)
HOOK_TEXT_BY_S = 0.5            # hook caption must be on screen by 0.5 s
HOOK_WINDOW_S = 3.0             # hook treatment covers the first 3 s only

# Number words that whisper hears as words but the script writes as digits.
_NUMBER_WORDS = {
    "two": "2,000", "thousand": "2,000",
}


def _clean(word: str) -> str:
    return word.strip(".,?!;:\"'()").lower()


def allowed_keywords(ledger=None) -> frozenset:
    """The only words that may ever be highlighted or scaled.

    Base set from ``caption_presets.HIGHLIGHTABLE`` plus, when a ledger is
    supplied, names / numbers / key terms taken from APPROVED (reviewed)
    claims in that ledger — stopwords excluded, never guessed. Without a
    ledger the base set alone applies.
    """
    allowed = set(HIGHLIGHTABLE)
    if ledger:
        claims = ledger.get("claims", []) if isinstance(ledger, dict) else ledger
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            if claim.get("reviewed_by") is None and claim.get("status") not in (
                    "KNOWN", "DEBATED"):
                continue
            text = str(claim.get("text", ""))
            for token in re.findall(r"[A-Za-z][A-Za-z\-']+|\d[\d,]*", text):
                clean = _clean(token)
                if clean and clean not in STOPWORDS and len(clean) > 2:
                    allowed.add(clean)
                if re.fullmatch(r"\d[\d,]*", token):
                    allowed.add(token)
    return frozenset(allowed)


def claim_keywords(claim: dict, ledger=None) -> frozenset:
    """Highlightable words for one ledger claim: its own words ∩ allowed set."""
    allowed = allowed_keywords(ledger)
    words = set()
    for token in re.findall(r"[A-Za-z][A-Za-z\-']+|\d[\d,]*", str(claim.get("text", ""))):
        clean = _clean(token)
        if clean in allowed:
            words.add(clean)
    return frozenset(words)


@dataclass(frozen=True)
class CaptionTreatment:
    """One caption treatment: a preset plus the treatment-level overrides.

    ``base_preset_slug`` names the preset in ``caption_presets.PRESETS``
    this treatment is built on. ``scale_emphasis`` is the font-size
    multiplier applied ONLY to highlighted words (1.0 = no scale).
    ``animation`` is one of "none" | "fade" | "karaoke"; karaoke here means
    the spoken word lights up in the highlight colour as it is said —
    a colour change, never a bounce.
    """

    name: str
    slug: str
    description: str
    base_preset_slug: str
    font_size: int
    margin_v: int
    max_words_per_event: int
    max_lines: int = 2
    animation: str = "none"
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    highlight_mode: str = "selective"   # "selective" | "karaoke"
    scale_emphasis: float = 1.0         # 1.0 = no scale on any word
    margin_l: int = 60
    margin_r: int = 60

    def base_preset(self):
        if _presets is not None:
            return _presets.PRESETS[self.base_preset_slug]
        raise RuntimeError("caption_presets unavailable (fallback in use)")


HOOK = CaptionTreatment(
    name="Hook",
    slug="hook",
    description=(
        "Largest type (96pt Montserrat ExtraBold) for the first 3 seconds "
        "only. 1-4 word groups, word-synced karaoke: the spoken word lights "
        "up in solar yellow as it is said; only highlightable words also "
        "get a subtle 1.15x scale pop. First event starts at 0.00s so text "
        "is on screen by 0.5s. No bounce on any word."
    ),
    base_preset_slug="viral",
    font_size=96,
    margin_v=520,
    max_words_per_event=4,
    animation="karaoke",
    highlight_mode="karaoke",
    scale_emphasis=1.15,
)

FACT = CaptionTreatment(
    name="Important Fact",
    slug="fact",
    description=(
        "An important fact grounded in one ledger claim id. 72pt Montserrat "
        "ExtraBold, up to 6 words per event, keyword colour highlight in "
        "solar yellow plus a subtle 1.12x scale on the key word/number "
        "only. Calm otherwise — no karaoke, no bounce."
    ),
    base_preset_slug="documentary",
    font_size=72,
    margin_v=460,
    max_words_per_event=6,
    animation="none",
    highlight_mode="selective",
    scale_emphasis=1.12,
)

NARRATION = CaptionTreatment(
    name="Ordinary Narration",
    slug="narration",
    description=(
        "Calm ordinary narration: 64pt Montserrat Medium, sentence case, "
        "1-4 word groups, gentle 120/150ms fade, selective keyword "
        "highlight only. No karaoke, no scale, no bounce — the caption "
        "stays out of the way of the story."
    ),
    base_preset_slug="minimal",
    font_size=64,
    margin_v=400,
    max_words_per_event=4,
    animation="fade",
    fade_in_ms=120,
    fade_out_ms=150,
    highlight_mode="selective",
    scale_emphasis=1.0,
)

TREATMENTS = {"hook": HOOK, "fact": FACT, "narration": NARRATION}


def get_treatment(slug: str) -> CaptionTreatment:
    """Return the treatment for ``slug`` (``hook`` | ``fact`` | ``narration``)."""
    try:
        return TREATMENTS[slug]
    except KeyError:
        raise ValueError(f"unknown caption treatment {slug!r}; "
                         f"expected one of {sorted(TREATMENTS)}") from None


# ---------------------------------------------------------------------------
# Word timings
# ---------------------------------------------------------------------------

def _merge_split_numbers(timed):
    """Merge whisper's split numbers: ``2`` + ``,000`` -> ``2,000``."""
    merged = []
    for w in timed:
        word = w["word"]
        if merged and re.fullmatch(r",\d+", word):
            prev = merged[-1]
            merged[-1] = {"word": prev["word"] + word,
                          "start": prev["start"], "end": w["end"]}
        else:
            merged.append(dict(w))
    return merged


def align_script_to_timings(script_text: str, timed_words):
    """Map whisper's heard words onto the script's written words.

    Returns a list of ``{"word", "start", "end"}`` whose ``word`` values
    are exactly the script's words (correct written forms) and whose
    timings come from the transcription. Unmatched script words get a
    timing interpolated between their timed neighbours, so no word is
    ever dropped and no timing is ever invented as a caption start.
    """
    script_words = script_text.split()
    timed = _merge_split_numbers(
        [{"word": str(w["word"]), "start": float(w["start"]),
          "end": float(w["end"])} for w in timed_words])
    if not timed:
        return estimate_word_timings(script_text, 0.0) if script_words else []
    # Sequential match with a small lookahead for mishearings.
    aligned, j = [], 0
    for i, sw in enumerate(script_words):
        clean_sw = _clean(sw)
        match = None
        for k in range(j, min(j + 4, len(timed))):
            if _clean(timed[k]["word"]) == clean_sw:
                match = k
                break
            # "two thousand" (heard) vs "2,000" (written), and vice versa.
            if clean_sw in ("2,000", "1,400") and _clean(timed[k]["word"]) in (
                    "2", "1", "two", "one"):
                match = k
                break
        if match is not None:
            aligned.append({"word": sw, "start": timed[match]["start"],
                            "end": timed[match]["end"]})
            j = match + 1
        else:
            aligned.append({"word": sw, "start": None, "end": None})
    # Interpolate the unmatched slots between timed neighbours.
    n = len(aligned)
    for i, w in enumerate(aligned):
        if w["start"] is not None:
            continue
        prev = next((aligned[k] for k in range(i - 1, -1, -1)
                     if aligned[k]["start"] is not None), None)
        nxt = next((aligned[k] for k in range(i + 1, n)
                    if aligned[k]["start"] is not None), None)
        if prev is not None and nxt is not None:
            gap = nxt["start"] - prev["end"]
            run = [k for k in range(i, n) if aligned[k]["start"] is None]
            slot = gap / max(1, len(run) + 1)
            pos = run.index(i) + 1
            w["start"] = prev["end"] + slot * pos
            w["end"] = w["start"] + max(0.05, slot * 0.8)
        elif prev is not None:
            w["start"] = prev["end"] + 0.05
            w["end"] = w["start"] + 0.25
        elif nxt is not None:
            w["end"] = max(0.05, nxt["start"] - 0.05)
            w["start"] = max(0.0, w["end"] - 0.25)
        else:
            w["start"], w["end"] = 0.0, 0.25
    # Final pass: keep timings monotone.
    last_end = 0.0
    for w in aligned:
        if w["start"] < last_end:
            w["start"] = last_end
        if w["end"] <= w["start"]:
            w["end"] = w["start"] + 0.1
        last_end = w["end"]
    return aligned


def estimate_word_timings(script_text: str, duration: float):
    """Deterministic evenly-spaced timings — fallback only, clearly labelled.

    Used when no transcription exists. Never presented as measured timings.
    """
    words = script_text.split()
    if not words:
        return []
    per = duration / len(words) if duration > 0 else 0.4
    return [{"word": w, "start": round(i * per, 3),
             "end": round((i + 1) * per - 0.03, 3)}
            for i, w in enumerate(words)]


_WHISPER_SCRIPT = r"""
import json, sys
import numpy as np
from faster_whisper import WhisperModel
audio = np.fromfile(sys.argv[1], dtype=np.float32)
model = WhisperModel(sys.argv[2], device="cpu", compute_type="int8")
segments, _info = model.transcribe(audio, language="en",
                                   word_timestamps=True, vad_filter=True)
words = []
for seg in segments:
    for w in (seg.words or []):
        words.append({"word": w.word.strip(), "start": float(w.start),
                      "end": float(w.end)})
json.dump(words, open(sys.argv[3], "w"))
print(len(words))
"""


def get_word_timings(audio_path: str, script_text: str | None = None,
                     model: str = "tiny") -> list:
    """Word timings from the narration audio via faster-whisper.

    The audio is decoded to 16 kHz mono float32 PCM with ffmpeg first
    and passed to faster-whisper as a numpy array — faster-whisper's
    ``decode_audio`` is broken against the installed PyAV, so the file
    path must never be handed to it directly. Runs in
    ``~/workspace/tts_venv`` (where faster-whisper 1.2.1 lives). If
    ``script_text`` is given, timings are aligned onto the script's
    words (see ``align_script_to_timings``); otherwise the raw heard
    words are returned.
    """
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"narration audio not found: {audio_path}")
    venv_python = TTS_VENV_PYTHON
    if not os.path.isfile(venv_python):
        venv_python = sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        pcm = os.path.join(tmp, "audio-16k.f32")
        out_json = os.path.join(tmp, "words.json")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", audio_path,
             "-ar", "16000", "-ac", "1", "-f", "f32le", pcm],
            check=True)
        result = subprocess.run(
            [venv_python, "-c", _WHISPER_SCRIPT, pcm, model, out_json],
            capture_output=True, text=True, check=True)
        with open(out_json, encoding="utf-8") as fh:
            timed = json.load(fh)
    if script_text:
        return align_script_to_timings(script_text, timed)
    return timed


# ---------------------------------------------------------------------------
# ASS generation
# ---------------------------------------------------------------------------

def _fmt(t: float) -> str:
    t = max(0.0, float(t))
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}.{int(round((t % 1) * 100)):02d}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")")


def _apply_case(word: str, treatment: CaptionTreatment, preset) -> str:
    return word.upper() if preset.case == "upper" else word


def _render_word(word: str, treatment: CaptionTreatment, preset,
                 allowed, highlight_words, base_size: int) -> str:
    """One word's ASS text. Colour/scale only if the word is allowed.

    Highlighted words get the solar-yellow colour; in hook/fact they
    additionally get a subtle ``\\fs`` scale pop (``scale_emphasis``).
    Every other word is plain — never coloured, never scaled, never bounced.
    """
    clean = _clean(word)
    text = _escape(_apply_case(word, treatment, preset))
    if clean in highlight_words and clean in allowed:
        if treatment.scale_emphasis and treatment.scale_emphasis != 1.0:
            big = int(round(base_size * treatment.scale_emphasis))
            return (f"{{\\fs{big}\\c{SOLAR_YELLOW}&}}{text}"
                    f"{{\\fs{base_size}\\c{WHITE}&}}")
        return f"{{\\c{SOLAR_YELLOW}&}}{text}{{\\c}}"
    return text


def _chunk_words(words, max_words: int):
    """Group timed words into events of <= ``max_words`` words.

    Cuts land just after a sentence-ending word when one falls at the
    boundary, otherwise at the balanced chunk size. Never mid-phrase
    except at the caller's window boundary.
    """
    events, i = [], 0
    while i < len(words):
        chunk = words[i:i + max_words]
        # Prefer ending on sentence punctuation if it is within the chunk.
        for k in range(len(chunk) - 1, 0, -1):
            if chunk[k]["word"].rstrip().endswith((".", "?", "!")):
                chunk = chunk[:k + 1]
                break
        events.append(chunk)
        i += len(chunk)
    return events


def _split_lines(words, max_lines: int = 2):
    """Split one event's words into at most ``max_lines`` display lines."""
    if len(words) <= 1 or max_lines <= 1:
        return [words]
    mid = len(words) // 2
    comma = [i for i, w in enumerate(words)
             if w["word"].rstrip().endswith(",")]
    near_mid = [i for i in comma if abs(i + 1 - mid) <= 2]
    cut = (near_mid[0] + 1) if near_mid else mid
    return [ln for ln in (words[:cut], words[cut:]) if ln]


def _event_text(event, treatment, preset, allowed, highlight_words,
                font_path, base_size, width):
    max_width = width - treatment.margin_l - treatment.margin_r
    line_words = _split_lines(event, treatment.max_lines)
    plain_lines = [" ".join(_apply_case(w["word"], treatment, preset)
                            for w in ln) for ln in line_words]
    size = fit_size(max(plain_lines, key=len), font_path, base_size, max_width)
    rendered = []
    for ln in line_words:
        if treatment.animation == "karaoke":
            parts = []
            for w in ln:
                dur_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
                parts.append(f"{{\\k{dur_cs}}}"
                             f"{_render_word(w['word'], treatment, preset, allowed, highlight_words, size)}")
            rendered.append(" ".join(parts))
        else:
            rendered.append(" ".join(
                _render_word(w["word"], treatment, preset, allowed,
                             highlight_words, size) for w in ln))
    text = "\\N".join(rendered)
    if size != base_size:
        # The fitted size only takes effect if applied to the whole event;
        # otherwise plain words would still render at the Style size.
        text = f"{{\\fs{size}}}" + text
    if treatment.animation == "fade":
        text = f"{{\\fad({treatment.fade_in_ms},{treatment.fade_out_ms})}}{text}"
    return text, size


def build_treatment_ass(treatment, words, path: str,
                        width: int = 1080, height: int = 1920,
                        highlight_words=None, ledger=None,
                        clamp_first_start_to: float | None = None) -> str:
    """Write an ASS caption file for ``treatment`` from timed ``words``.

    ``words``: list of ``{"word", "start", "end"}`` (see
    ``get_word_timings`` / ``align_script_to_timings``). ``highlight_words``
    defaults to the treatment's base preset highlight set; pass a
    claim-specific set for fact captions. ``clamp_first_start_to`` forces
    the first event to start no later than that time (the hook treatment
    passes 0.0 so text is on screen by 0.5 s even if narration starts
    late). Returns the written path. Deterministic.
    """
    if isinstance(treatment, str):
        treatment = get_treatment(treatment)
    if _presets is not None:
        preset = treatment.base_preset()
        font_name, font_path, _bundled = resolve_font(preset)
        case = preset.case
        spacing, outline, shadow = (preset.letter_spacing,
                                    preset.outline_width, preset.shadow_depth)
    else:  # minimal fallback definition (see module docstring)
        font_name, font_path = "Montserrat ExtraBold", os.path.join(
            FONT_DIR, "Montserrat-ExtraBold.ttf")
        case = "upper"
        spacing, outline, shadow = 1.0, 5, 3

    class _P:  # tiny stand-in so _render_word/_event_text stay uniform
        pass
    _p = _P()
    _p.case = case
    allowed = allowed_keywords(ledger)
    if highlight_words is None:
        highlight_words = (treatment.base_preset().highlight_words
                           if _presets is not None else frozenset())
    highlight_words = frozenset(w for w in highlight_words if w in allowed)

    size = int(round(treatment.font_size * width / 1080))
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
        f"Style: {treatment.name},{font_name},{size},{WHITE},"
        f"{SOLAR_YELLOW},{BLACK},{SHADOW_BLACK},0,0,0,0,100,100,"
        f"{spacing:.1f},0,1,{outline},{shadow},2,{treatment.margin_l},"
        f"{treatment.margin_r},{treatment.margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text",
    ]
    events = _chunk_words(words, treatment.max_words_per_event)
    for idx, event in enumerate(events):
        start = event[0]["start"]
        end = event[-1]["end"]
        if idx == 0 and clamp_first_start_to is not None:
            start = min(start, clamp_first_start_to)
        text, _used = _event_text(event, treatment, _p, allowed,
                                  highlight_words, font_path, size, width)
        lines.append(
            f"Dialogue: 0,{_fmt(start)},{_fmt(end)},{treatment.name},,0,0,0,,{text}"
        )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def build_hook_ass(words, path: str, width: int = 1080, height: int = 1920,
                   ledger=None, window_s: float = HOOK_WINDOW_S) -> str:
    """Hook treatment ASS for the first ``window_s`` seconds of narration.

    Only words starting before ``window_s`` are rendered, in 1-4 word
    groups, first event clamped to 0.00 s. The hook plan's 2-5 word
    opening text is a separate title overlay — see
    ``src.hook.opening_text_event`` — not a caption, so it never
    collides with these word-synced captions.
    """
    first = [w for w in words if w["start"] < window_s]
    if not first:
        raise ValueError("no narration words start inside the first "
                         f"{window_s}s hook window")
    return build_treatment_ass(HOOK, first, path, width=width, height=height,
                               ledger=ledger, clamp_first_start_to=0.0)


def build_fact_ass(words, path: str, claim_id: str, ledger,
                   width: int = 1080, height: int = 1920) -> str:
    """Fact treatment ASS, grounded in one ledger claim.

    ``claim_id`` must exist in ``ledger`` and be a reviewed KNOWN claim;
    otherwise ``ValueError`` — a fact caption is never built on an
    unverified or unknown claim.
    """
    claims = ledger.get("claims", []) if isinstance(ledger, dict) else ledger
    claim = next((c for c in claims if c.get("claim_id") == claim_id), None)
    if claim is None:
        raise ValueError(f"claim {claim_id!r} not found in the evidence ledger")
    if claim.get("status") != "KNOWN":
        raise ValueError(
            f"claim {claim_id!r} has status {claim.get('status')!r}, not "
            "'KNOWN' — a fact caption must be grounded in a verified claim")
    if not claim.get("reviewed_by"):
        raise ValueError(f"claim {claim_id!r} has no reviewer — not verified")
    keywords = claim_keywords(claim, ledger)
    return build_treatment_ass(FACT, words, path, width=width, height=height,
                               highlight_words=keywords, ledger=ledger)


def build_narration_ass(words, path: str, width: int = 1080,
                        height: int = 1920, ledger=None) -> str:
    """Ordinary-narration treatment ASS: calm, no karaoke, no scale."""
    return build_treatment_ass(NARRATION, words, path, width=width,
                               height=height, ledger=ledger)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_treatment(treatment, width: int = 1080,
                       height: int = 1920) -> list:
    """Return a list of problems with ``treatment`` (empty = valid)."""
    if isinstance(treatment, str):
        treatment = get_treatment(treatment)
    problems = []
    if treatment.max_lines != 2:
        problems.append(f"max_lines is {treatment.max_lines}, must be 2")
    if treatment.font_size < 24 or treatment.font_size > 120:
        problems.append(f"font_size {treatment.font_size} outside 24-120")
    if treatment.max_words_per_event < 1 or treatment.max_words_per_event > 9:
        problems.append(f"max_words_per_event {treatment.max_words_per_event} "
                        "outside 1-9")
    if treatment.margin_l < SAFE_MARGIN_LR or treatment.margin_r < SAFE_MARGIN_LR:
        problems.append("side margins below safe-zone minimum "
                        f"{SAFE_MARGIN_LR}px")
    if not (SAFE_MARGIN_V_MIN <= treatment.margin_v <= SAFE_MARGIN_V_MAX):
        problems.append(f"margin_v {treatment.margin_v} outside safe band "
                        f"{SAFE_MARGIN_V_MIN}-{SAFE_MARGIN_V_MAX} "
                        "(caption band ~70-80% down the frame)")
    if treatment.animation not in ("none", "fade", "karaoke"):
        problems.append(f"unknown animation {treatment.animation!r}")
    if treatment.highlight_mode not in ("selective", "karaoke"):
        problems.append(f"unknown highlight_mode {treatment.highlight_mode!r}")
    if treatment.slug == "narration" and (
            treatment.scale_emphasis != 1.0
            or treatment.animation == "karaoke"):
        problems.append("narration treatment must not scale or karaoke words")
    if _presets is not None:
        preset = treatment.base_preset()
        problems.extend(
            f"base preset {preset.slug}: {p}"
            for p in _presets.validate_preset(preset, width, height)
            if "margin_v" not in p)  # treatment overrides margin_v itself
    return problems


def parse_ass_dialogues(path: str):
    """Parse an ASS file's Dialogue lines into dicts."""
    dialogues = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.startswith("Dialogue:"):
                continue
            parts = line.split(",", 9)
            if len(parts) < 10:
                continue
            dialogues.append({
                "layer": parts[0].split(":", 1)[1].strip(),
                "start": parts[1], "end": parts[2], "style": parts[3],
                "text": parts[9],
            })
    return dialogues


def _ass_time_to_s(text: str) -> float:
    h, m, rest = text.split(":")
    s, cs = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100.0


def validate_ass_file(path: str, width: int = 1080, height: int = 1920,
                      allowed=None, require_first_by: float | None = None,
                      font_path: str | None = None) -> list:
    """Validate a written ASS file. Returns a list of problems (empty = OK).

    Checks: at least one Dialogue; max two lines per event; first event
    starts by ``require_first_by`` when given; every coloured/scaled
    word is in the allowed keyword set; every line's measured width
    fits inside the safe side margins.
    """
    problems = []
    dialogues = parse_ass_dialogues(path)
    if not dialogues:
        return ["no Dialogue events in ASS file"]
    # Style fontsize from the file header: the default size when an event
    # carries no leading {\fs} fit override.
    style_size = 72
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("Style:"):
                fields = line.split(",")
                try:
                    style_size = int(fields[2])
                except (IndexError, ValueError):
                    pass
                break
    if require_first_by is not None:
        first_start = _ass_time_to_s(dialogues[0]["start"])
        if first_start > require_first_by:
            problems.append(f"first caption starts at {first_start}s, "
                            f"after {require_first_by}s")
    allowed = allowed if allowed is not None else HIGHLIGHTABLE
    font_path = font_path or os.path.join(FONT_DIR, "Montserrat-ExtraBold.ttf")
    for d in dialogues:
        lines = d["text"].split("\\N")
        if len(lines) > 2:
            problems.append(f"event at {d['start']} has {len(lines)} lines")
        plain = re.sub(r"\{[^}]*\}", "", d["text"]).replace("\\N", " ")
        # Effective size: a leading {\fsN} fit override at the very start
        # of the event (after an optional {\fad} wrap) governs the whole
        # event; otherwise the Style fontsize applies. A mid-text {\fsN}
        # is a highlight scale on one word only and must NOT size the line.
        stripped = re.sub(r"^\{\\fad\([^)]*\)\}", "", d["text"])
        fs_match = re.match(r"\{\\fs(\d+)", stripped)
        eff_size = int(fs_match.group(1)) if fs_match else style_size
        for ln in lines:
            clean_line = re.sub(r"\{[^}]*\}", "", ln)
            if measure_width(clean_line, font_path, eff_size) > (
                    width - 2 * SAFE_MARGIN_LR):
                problems.append(
                    f"line at {d['start']} wider than the safe zone "
                    f"at {eff_size}pt: {clean_line[:40]!r}")
        # Coloured words: every {\c...} override must wrap an allowed word.
        for match in re.finditer(r"\{\\c[^}]*\}([^{}]+)\{\\c\}", d["text"]):
            word = _clean(match.group(1))
            if word and word not in allowed:
                problems.append(f"highlighted word {word!r} not in allowed set")
        # Scaled words: a {\fsN\c...} override (highlight scale) must wrap
        # an allowed word. A bare leading {\fsN} is the whole-event fit
        # wrap applied by the render path, not a word scale — it has no
        # \c, so it is excluded by requiring \c in the override.
        for match in re.finditer(r"\{\\fs\d+\\c[^}]*\}([^{}]+)\{",
                                 d["text"]):
            word = _clean(match.group(1))
            if word and word not in allowed:
                problems.append(f"scaled word {word!r} not in allowed set")
    return problems
