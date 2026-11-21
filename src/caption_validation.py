"""Validation helpers for QA caption and visual-manifest checks (src/qa.py).

These are pure parsing/validation functions (no ffmpeg, no rendering)
so they can be unit-tested directly; src/qa.py wires them into
run_qa()/check() as individually reported checks.

Caption rules (see src/qa.py check names):
- captions_cover_script: every script word appears exactly once, in
  order, in the .ass Dialogue events. Trailing extra words AFTER the
  last script word are allowed and reported (the subscribe close,
  e.g. "LIKE AND SUBSCRIBE FOR MORE!", is appended after the body
  captions by make_ass(extra_captions=...)); an unexpected word
  before the script sequence is complete fails (missing, duplicated,
  or out-of-order words all surface here).
- captions_cover_duration: first event starts <= 0.5 s, last event
  ends >= (duration - 1.0 s), largest gap between consecutive events
  <= 2.0 s.
- captions_timing: with word timings, each body event's start/end
  must fall within +/-0.25 s of the corresponding words' times
  (events are mapped to script words in order; script-word spans
  come from src.video.align_script_to_timings, which aligns script
  spellings onto the transcribed tokens). Without timings, events
  must be monotonic, non-overlapping, and inside [0, duration] --
  and the check records that timing-vs-audio was NOT verified.

Normalization (documented, deterministic): words are lowercased;
every character except a-z, 0-9 and an apostrophe is stripped
(curly apostrophes are folded to ASCII first), and leading/trailing
apostrophes are stripped. So "Ago." -> "ago", "museum's" stays
"museum's", "1,400" -> "1400". Digits are kept as written: a
caption that says "2,000" where the script says "two thousand"
does NOT match -- captions must use the script spellings, which is
what make_ass() writes (its TEXT always comes from the script).

Visual-manifest rules (schema written by src/video.py build_video
next to every render at <output>.visuals.json):
  {"duration": float,
   "chunks": [{"start": float, "end": float,
               "source": "real"|"gradient", "asset": str|null}, ...],
   "real_seconds": float, "gradient_seconds": float}
- real_visuals_present: FAIL if the manifest is missing/unreadable/
  malformed, or if real_seconds == 0 (gradient-only render).
- visual_coverage: FAIL if gradient_seconds > max(2.0 s, 5% of the
  video duration). A render may therefore carry at most 2 seconds
  (or 5% of its duration, whichever is larger) of gradient fallback.
The stated real/gradient totals must also agree with the chunk sums
(within 0.5 s) and real+gradient must agree with the manifest
duration (within 1.0 s); a manifest that disagrees with itself is
a schema/integrity failure, not something QA silently adapts to.
"""

import json
import os
import re

# --- caption tolerances (see module docstring) ---------------------------
CAPTION_FIRST_START_MAX = 0.5    # first event must start by this time
CAPTION_LAST_END_SLACK = 1.0     # last event must end by duration - this
CAPTION_MAX_GAP = 2.0            # largest allowed gap between events
CAPTION_TIMING_TOLERANCE = 0.25  # event start/end vs word times
CAPTION_OVERLAP_EPSILON = 0.02   # .ass times are centisecond-rounded

# --- visual-manifest tolerances ------------------------------------------
VISUAL_GRADIENT_MIN_TOLERANCE = 2.0   # seconds of gradient always allowed
VISUAL_GRADIENT_FRACTION = 0.05       # ... or 5% of duration, if larger
VISUAL_TOTAL_TOLERANCE = 0.5          # chunk sums vs stated totals
VISUAL_DURATION_TOLERANCE = 1.0       # totals/manifest duration agreement


def normalize_word(word):
    """Lowercase; strip everything except a-z/0-9/apostrophe.

    "Ago." -> "ago"; "museum's" -> "museum's"; "1,400" -> "1400".
    A token that normalizes to "" (pure punctuation) returns "".
    """
    cleaned = word.replace("\u2019", "'").replace("\u2018", "'").lower()
    cleaned = re.sub(r"[^a-z0-9']", "", cleaned)
    return cleaned.strip("'")


_ASS_TIME_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})\.(\d{2})$")
_ASS_TAG_RE = re.compile(r"\{[^}]*\}")


def strip_ass_tags(text):
    """Strip ASS override blocks and line-break escapes from event text.

    Production (Modern Documentary preset) captions carry inline
    formatting: highlight words are wrapped in colour overrides such
    as ``{\\c&H00CCFF&}BRONZE{\\c&H00FFFFFF&}`` and multi-line events
    join lines with ``\\N``. Word extraction must see the plain words
    (``BRONZE MACHINE``), not the formatting — otherwise the override
    letters/digits glue onto the adjacent word and QA fails a correct
    caption file. ``\\h`` (hard space) also becomes a plain space.
    """
    text = _ASS_TAG_RE.sub("", text)
    return (text.replace("\\N", " ").replace("\\n", " ")
                .replace("\\h", " "))


def parse_ass_time(text):
    """Parse an .ass H:MM:SS.cc timestamp to seconds (float)."""
    match = _ASS_TIME_RE.match(text.strip())
    if not match:
        raise ValueError(f"bad .ass timestamp: {text!r}")
    hours, minutes, seconds, centis = (int(g) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + centis / 100.0


def parse_ass(path):
    """Parse an .ass file into [(start, end, text), ...] Dialogue events.

    Raises FileNotFoundError if the file is missing, ValueError if it
    has no Dialogue events or a malformed Dialogue line.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"captions file missing: {path}")
    events = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.startswith("Dialogue:"):
                continue
            fields = line.split("Dialogue:", 1)[1].strip().split(",", 9)
            if len(fields) < 10:
                raise ValueError(f"malformed Dialogue line: {line!r}")
            start = parse_ass_time(fields[1])
            end = parse_ass_time(fields[2])
            events.append((start, end, fields[9].strip()))
    if not events:
        raise ValueError(f"no Dialogue events in captions file: {path}")
    return events


def caption_words(events):
    """All caption words in order (raw case/punctuation preserved).

    ASS override tags and ``\\N`` breaks are stripped first (see
    strip_ass_tags) so preset highlight formatting never pollutes
    the word list.
    """
    words = []
    for _, _, text in events:
        words.extend(strip_ass_tags(text).split())
    return words


def load_word_timings(source):
    """Load word timings as [(start, end, word), ...].

    `source` is a path to a JSON file or an already-loaded list.
    Accepted JSON shapes (both occur in this repo):
    - [[start, end, word], ...]  (word_timings_final.json)
    - [{"word": ..., "start": ..., "end": ...}, ...]
      (tests/fixtures/antikythera-words.json; "text" is also accepted
      as the word key)
    Raises ValueError on a bad shape, FileNotFoundError on a bad path.
    """
    if isinstance(source, (str, os.PathLike)):
        if not os.path.exists(source):
            raise FileNotFoundError(f"word-timings file missing: {source}")
        with open(source, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = source
    if not isinstance(data, list):
        raise ValueError("word timings must be a JSON list")
    timings = []
    for entry in data:
        if isinstance(entry, dict):
            word = entry.get("word", entry.get("text"))
            start = entry.get("start", entry.get("start_time"))
            end = entry.get("end", entry.get("end_time"))
        elif isinstance(entry, (list, tuple)) and len(entry) == 3:
            start, end, word = entry
        else:
            raise ValueError(f"bad word-timing entry: {entry!r}")
        if word is None or start is None or end is None:
            raise ValueError(f"bad word-timing entry: {entry!r}")
        timings.append((float(start), float(end), str(word)))
    if not timings:
        raise ValueError("word timings are empty")
    return timings


def check_cover_script(events, script_words):
    """captions_cover_script: every script word once, in order.

    Returns (passed, detail). Trailing extra words after the last
    script word are allowed and counted in the detail (subscribe
    close); any other unexpected word fails.
    """
    script_norm = [normalize_word(w) for w in script_words]
    script_norm = [w for w in script_norm if w]
    cap = caption_words(events)
    cap_norm = [normalize_word(w) for w in cap]
    cap_norm = [w for w in cap_norm if w]
    idx = 0
    for pos, word in enumerate(cap_norm):
        if idx < len(script_norm):
            if word == script_norm[idx]:
                idx += 1
            else:
                expected = script_norm[idx]
                got = cap[pos] if pos < len(cap) else word
                return False, (
                    f"caption word {pos + 1} {got!r} does not match "
                    f"script word {idx + 1} {script_words[idx]!r} "
                    f"(expected {expected!r}): script words missing, "
                    f"duplicated, or out of order "
                    f"({idx}/{len(script_norm)} script words matched)")
        # else: all script words matched; remaining words are trailing extras.
    trailing = len(cap_norm) - idx
    if idx < len(script_norm):
        missing = script_words[idx:idx + 5]
        return False, (
            f"only {idx}/{len(script_norm)} script words appear in "
            f"captions; first missing: {missing}")
    detail = (f"{idx}/{len(script_norm)} script words appear exactly "
              f"once, in order ({len(cap_norm)} caption words total)")
    if trailing:
        detail += (f"; +{trailing} trailing extra word(s) after the "
                   f"script end (e.g. subscribe close)")
    return True, detail


def check_cover_duration(events, duration):
    """captions_cover_duration: start/gap/end coverage vs `duration`.

    Returns (passed, detail).
    """
    first_start = events[0][0]
    last_end = events[-1][1]
    gaps = [(events[i + 1][0] - events[i][1], i)
            for i in range(len(events) - 1)]
    max_gap, gap_idx = max(gaps) if gaps else (0.0, -1)
    problems = []
    if first_start > CAPTION_FIRST_START_MAX:
        problems.append(f"first event starts at {first_start:.2f}s "
                        f"(must be <= {CAPTION_FIRST_START_MAX}s)")
    if last_end < duration - CAPTION_LAST_END_SLACK:
        problems.append(f"last event ends at {last_end:.2f}s "
                        f"(must be >= {duration - CAPTION_LAST_END_SLACK:.1f}s "
                        f"for a {duration:.1f}s narration)")
    if max_gap > CAPTION_MAX_GAP:
        problems.append(f"largest gap between events is {max_gap:.2f}s "
                        f"(after event {gap_idx + 1}; "
                        f"must be <= {CAPTION_MAX_GAP}s)")
    if problems:
        return False, "; ".join(problems)
    return True, (f"first event at {first_start:.2f}s, last ends at "
                  f"{last_end:.2f}s of {duration:.1f}s, largest gap "
                  f"{max_gap:.2f}s")


def check_timing(events, script_words, word_timings=None, duration=None):
    """captions_timing: event times vs the spoken words.

    With word timings: each body event's start/end must fall within
    +/-0.25 s of the corresponding script words' times (events are
    consumed in order; trailing extra events with no script words
    left, e.g. the subscribe close, are skipped and noted).
    Without timings: events must be monotonic, non-overlapping, and
    inside [0, duration] -- and the detail records that timing
    vs audio was NOT verified.

    Returns (passed, detail, verified_vs_audio).
    """
    if word_timings is None:
        problems = []
        prev_end = None
        for i, (start, end, _) in enumerate(events):
            if end <= start:
                problems.append(f"event {i + 1} has end <= start "
                                f"({start:.2f}s-{end:.2f}s)")
            if start < 0:
                problems.append(f"event {i + 1} starts before 0 "
                                f"({start:.2f}s)")
            if duration is not None and end > duration + 0.1:
                problems.append(f"event {i + 1} ends at {end:.2f}s, "
                                f"past the {duration:.1f}s duration")
            if prev_end is not None and start < prev_end - CAPTION_OVERLAP_EPSILON:
                problems.append(f"event {i + 1} starts at {start:.2f}s "
                                f"before event {i} ends at {prev_end:.2f}s "
                                f"(overlap)")
            prev_end = end if prev_end is None else max(prev_end, end)
        if problems:
            return False, "; ".join(problems[:5]), False
        return True, ("events are monotonic, non-overlapping, and inside "
                      "[0, duration]; timing-vs-audio NOT verified "
                      "(no word timings supplied)"), False
    try:
        from src.video import align_script_to_timings
    except ImportError:
        from video import align_script_to_timings
    script_norm = [w for w in script_words if normalize_word(w)]
    aligned = align_script_to_timings(script_norm, word_timings)
    if len(aligned) != len(script_norm):
        return False, (f"alignment returned {len(aligned)} word spans "
                       f"for {len(script_norm)} script words"), True
    idx = 0
    violations = []
    extra_events = 0
    worst = 0.0
    for ei, (start, end, text) in enumerate(events):
        # Strip preset override tags / \N breaks before counting words
        # (same treatment as caption_words, else a highlighted word
        # counts as a tag-glued token and the mapping derails).
        words = strip_ass_tags(text).split()
        if idx + len(words) > len(script_norm):
            extra_events += 1
            continue
        spans = aligned[idx:idx + len(words)]
        start_diff = abs(start - spans[0][0])
        end_diff = abs(end - spans[-1][1])
        worst = max(worst, start_diff, end_diff)
        if (start_diff > CAPTION_TIMING_TOLERANCE
                or end_diff > CAPTION_TIMING_TOLERANCE):
            violations.append(
                f"event {ei + 1} {text!r} ({start:.2f}s-{end:.2f}s) vs "
                f"words {spans[0][0]:.2f}s-{spans[-1][1]:.2f}s "
                f"(start off {start_diff:.2f}s, end off {end_diff:.2f}s)")
        idx += len(words)
    if idx < len(script_norm):
        return False, (f"caption events cover only {idx}/"
                       f"{len(script_norm)} script words; "
                       f"{len(script_norm) - idx} word(s) have no timed "
                       f"caption event"), True
    if violations:
        return False, ("; ".join(violations[:5])
                       + (f"; +{len(violations) - 5} more" if len(violations) > 5 else "")), True
    detail = (f"{len(events) - extra_events} event(s) within "
              f"+/-{CAPTION_TIMING_TOLERANCE}s of the spoken words "
              f"(worst deviation {worst:.2f}s)")
    if extra_events:
        detail += (f"; {extra_events} trailing event(s) not covered by "
                   f"word timings (e.g. subscribe close)")
    return True, detail, True


def load_visual_manifest(path):
    """Load and schema-validate a <output>.visuals.json manifest.

    Returns the manifest dict. Raises FileNotFoundError if missing,
    ValueError with a specific reason if the JSON/shape is wrong.
    The schema is exactly:
      {"duration": float,
       "chunks": [{"start": float, "end": float,
                   "source": "real"|"gradient", "asset": str|null}],
       "real_seconds": float, "gradient_seconds": float}
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"visual manifest missing: {path}")
    with open(path, encoding="utf-8") as fh:
        try:
            manifest = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"visual manifest is not valid JSON: {exc}")
    if not isinstance(manifest, dict):
        raise ValueError("visual manifest must be a JSON object")
    for key in ("duration", "chunks", "real_seconds", "gradient_seconds"):
        if key not in manifest:
            raise ValueError(f"visual manifest missing key: {key!r}")
    duration = manifest["duration"]
    chunks = manifest["chunks"]
    real_seconds = manifest["real_seconds"]
    gradient_seconds = manifest["gradient_seconds"]
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError(f"visual manifest 'duration' must be a "
                         f"positive number, got {duration!r}")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("visual manifest 'chunks' must be a non-empty list")
    if not isinstance(real_seconds, (int, float)) or real_seconds < 0:
        raise ValueError(f"visual manifest 'real_seconds' must be a "
                         f"non-negative number, got {real_seconds!r}")
    if not isinstance(gradient_seconds, (int, float)) or gradient_seconds < 0:
        raise ValueError(f"visual manifest 'gradient_seconds' must be a "
                         f"non-negative number, got {gradient_seconds!r}")
    for i, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise ValueError(f"visual manifest chunk {i} is not an object")
        for key in ("start", "end", "source"):
            if key not in chunk:
                raise ValueError(f"visual manifest chunk {i} missing "
                                 f"key: {key!r}")
        start, end = chunk["start"], chunk["end"]
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError(f"visual manifest chunk {i} start/end must "
                             f"be numbers")
        if not (0 <= start < end <= duration + VISUAL_DURATION_TOLERANCE):
            raise ValueError(f"visual manifest chunk {i} has an invalid "
                             f"span: {start!r}-{end!r} for duration "
                             f"{duration!r}")
        if chunk["source"] not in ("real", "gradient"):
            raise ValueError(f"visual manifest chunk {i} has unknown "
                             f"source: {chunk['source']!r} (must be "
                             f"'real' or 'gradient')")
        if "asset" in chunk and chunk["asset"] is not None \
                and not isinstance(chunk["asset"], str):
            raise ValueError(f"visual manifest chunk {i} 'asset' must be "
                             f"a string or null")
    return manifest


def check_visual_manifest(manifest, video_duration=None):
    """Apply the visual-manifest rules to a loaded manifest dict.

    Returns (real_ok, real_detail, coverage_ok, coverage_detail).
    A manifest whose stated totals disagree with its chunks, or whose
    duration disagrees with the video, fails both checks as a
    schema/integrity failure.
    """
    duration = float(manifest["duration"])
    chunks = manifest["chunks"]
    real_seconds = float(manifest["real_seconds"])
    gradient_seconds = float(manifest["gradient_seconds"])
    real_sum = sum(c["end"] - c["start"] for c in chunks
                   if c["source"] == "real")
    gradient_sum = sum(c["end"] - c["start"] for c in chunks
                       if c["source"] == "gradient")
    integrity = []
    if abs(real_sum - real_seconds) > VISUAL_TOTAL_TOLERANCE:
        integrity.append(f"real_seconds {real_seconds:.2f}s disagrees "
                         f"with chunk sum {real_sum:.2f}s")
    if abs(gradient_sum - gradient_seconds) > VISUAL_TOTAL_TOLERANCE:
        integrity.append(f"gradient_seconds {gradient_seconds:.2f}s "
                         f"disagrees with chunk sum {gradient_sum:.2f}s")
    if abs((real_seconds + gradient_seconds) - duration) > VISUAL_DURATION_TOLERANCE:
        integrity.append(f"real+gradient ({real_seconds + gradient_seconds:.2f}s) "
                         f"disagrees with manifest duration {duration:.2f}s")
    if video_duration is not None and abs(duration - video_duration) > VISUAL_DURATION_TOLERANCE:
        integrity.append(f"manifest duration {duration:.2f}s disagrees "
                         f"with video duration {video_duration:.2f}s")
    if integrity:
        detail = "visual manifest integrity failure: " + "; ".join(integrity)
        return False, detail, False, detail
    base = (f"real {real_seconds:.2f}s / gradient {gradient_seconds:.2f}s "
            f"of {duration:.2f}s")
    if real_seconds <= 0:
        real_detail = base + " -- gradient-only render (real_seconds == 0)"
        return False, real_detail, False, real_detail
    real_detail = base
    span = video_duration if video_duration is not None else duration
    tolerance = max(VISUAL_GRADIENT_MIN_TOLERANCE,
                    VISUAL_GRADIENT_FRACTION * span)
    rule = (f"gradient {gradient_seconds:.2f}s vs tolerance "
            f"max(2.0s, 5% of {span:.1f}s) = {tolerance:.2f}s")
    if gradient_seconds > tolerance:
        return True, real_detail, False, (
            f"gradient_seconds {gradient_seconds:.2f}s exceeds {rule}")
    return True, real_detail, True, f"{base}; {rule} -- within tolerance"
