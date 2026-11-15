"""Rule-based candidate-claim extraction from research source records.

Phase 2D of the Deep Scan evidence engine. This module turns the
abstracts of already-filtered discovery candidates into *candidate*
claims for the human reviewer. It is deliberately narrow:

* Input is source records exactly as produced by ``src.research`` /
  ``src.relevance`` (title, abstract text or OpenAlex
  ``abstract_inverted_index``, ``source_id``, ``source_type``).
  Only sources that passed relevance filtering are extracted from --
  see :func:`extract_from_discovery`, which reads only the ``sources``
  (kept) list of a discovery result and ignores ``dropped_sources``.
* Extracted text is always a verbatim sentence from the source
  abstract. Nothing is paraphrased, completed, or invented: every
  candidate ``text`` is a substring of its source text.
* The suggested tier defaults to UNKNOWN. KNOWN is suggested only
  for a sentence stating a published measurement or finding from a
  ``primary``/``academic`` source, and the suggestion is still
  unreviewed. DEBATED is never suggested -- judging a disagreement
  needs a human.
* Nothing here approves a source or a claim, writes to the evidence
  ledger, or changes a tier. Candidates are returned for the review
  packet; a claim only enters the ledger when a human confirms it
  (fills ``reviewed_by``/``reviewed_at``, sets the final tier, sets
  ``include_in_script``).

Pure standard library, no I/O, no network, deterministic.
"""
import re

EXTRACTION_METHOD = "abstract_sentence"

# A candidate sentence must contain at least one content term from the
# topic and a verifiable predicate: a measurement, a year/date, or a
# finding verb. Generic prose ("researchers have long wondered...")
# has neither and is never extracted.
_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "for", "and", "or", "to", "with",
    "by", "from", "at", "is", "are", "was", "were", "it", "its", "as",
    "into", "over", "under", "after", "before", "between", "through",
    "during", "about", "against", "within", "without", "upon", "per",
    "via", "de", "la", "le", "et", "und", "der", "die", "das",
}

_PREDICATE_VERBS = {
    "discovered", "revealed", "measured", "contains", "contain",
    "shows", "show", "predicted", "predicts", "identified", "found",
    "reported", "observed", "dated", "constructed", "built",
    "demonstrates", "indicates", "recorded", "doubled", "confirmed",
    "calculated", "displayed", "survives", "survived",
}

_MEASUREMENT_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:%|percent|years?|months?|days?|weeks?|"
    r"metres?|meters?|kilometres?|kilometers?|cm|mm|km|"
    r"fragments?|gears?|characters?|letters?|teeth|centuries?|"
    r"sections?|turns?)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")

# Abbreviations whose full stops must not split a sentence.
_ABBREVIATIONS = (
    "e.g.", "i.e.", "et al.", "U.S.", "U.K.", "Dr.", "St.", "No.",
    "Fig.", "vs.", "Mt.", "Prof.",
)

try:  # pragma: no cover - import path depends on caller
    from src.relevance import abstract_text as _relevance_abstract_text
except ImportError:  # pragma: no cover - direct module execution
    try:
        from relevance import abstract_text as _relevance_abstract_text
    except ImportError:
        _relevance_abstract_text = None


def source_text(source):
    """Plain-text abstract for a source record, or "" when it has none.

    Prefers an explicit ``abstract`` string, then rebuilds an OpenAlex
    abstract from ``abstract_inverted_index`` (via ``src.relevance``).
    A record with no abstract yields no claims -- never a crash, never
    a guess.
    """
    if not isinstance(source, dict):
        return ""
    abstract = source.get("abstract")
    if isinstance(abstract, str) and abstract.strip():
        return abstract.strip()
    if _relevance_abstract_text is not None:
        return _relevance_abstract_text(source)
    index = source.get("abstract_inverted_index") or {}
    if not isinstance(index, dict) or not index:
        return ""
    placed = []
    for word, positions in index.items():
        for position in positions or []:
            try:
                placed.append((int(position), str(word)))
            except (TypeError, ValueError):
                continue
    placed.sort()
    return " ".join(word for _, word in placed)


def split_sentences(text):
    """Split text into sentences, guarding decimals and abbreviations.

    Splits only on a sentence-final ``.``/``!``/``?`` followed by
    whitespace and a capital letter, digit, or opening quote, so
    "18.2 years" and "e.g. the dial" stay intact.
    """
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []
    protected = text
    for abbr in _ABBREVIATIONS:
        protected = protected.replace(abbr, abbr.replace(".", "\x00"))
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\(\"“])", protected)
    return [p.replace("\x00", ".").strip() for p in parts if p.strip()]


def _content_terms(topic):
    """Topic terms that must appear in a candidate sentence."""
    return [t for t in re.split(r"[^a-z0-9]+", (topic or "").lower())
            if t and t not in _STOPWORDS]


def _has_verifiable_predicate(sentence):
    """True when the sentence states something checkable: a measurement,
    a year/date, or a finding verb."""
    if _MEASUREMENT_RE.search(sentence) or _YEAR_RE.search(sentence):
        return True
    lowered = " " + sentence.lower() + " "
    if any(re.search(r"\b" + re.escape(verb) + r"\b", lowered)
           for verb in _PREDICATE_VERBS):
        return True
    if re.search(r"\b(more than|at least|over|under)\s+\d", sentence,
                 re.IGNORECASE):
        return True
    return False


def _suggest_status(sentence, source_type):
    """Tier suggestion only. KNOWN only for a measurement/finding
    sentence from a primary/academic source; otherwise UNKNOWN.
    DEBATED is never suggested. The suggestion is unreviewed either
    way -- a human still sets the final tier."""
    if (source_type or "").lower() in ("primary", "academic") \
            and _has_verifiable_predicate(sentence):
        return "KNOWN"
    return "UNKNOWN"


def _normalize_sentence(sentence):
    return re.sub(r"\s+", " ", sentence.lower()).strip(" .")


def extract_claims(sources, topic, max_per_source=10):
    """Extract candidate claims from filtered source records.

    ``sources`` is the kept list from discovery (already relevance
    filtered); ``topic`` is the documentary topic string. Returns a
    list of candidate dicts in deterministic source/sentence order.
    The same factual sentence appearing in two sources is merged into
    one candidate linking both ``source_ids``. Every candidate is
    unreviewed (``review_status`` UNREVIEWED, blank reviewer fields,
    ``include_in_script`` False) -- extraction never approves anything.
    """
    terms = _content_terms(topic)
    if not terms:
        # No topic, no extraction: candidates must be about something.
        return []
    candidates = {}
    order = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        if not source_id:
            continue
        text = source_text(source)
        if not text:
            continue
        source_type = (source.get("source_type") or "other").lower()
        kept = 0
        for sentence in split_sentences(text):
            if kept >= max_per_source:
                break
            if len(sentence.split()) < 4:
                continue
            lowered = sentence.lower()
            if terms and not any(
                    re.search(r"\b" + re.escape(term) + r"\b", lowered)
                    for term in terms):
                continue
            if not _has_verifiable_predicate(sentence):
                continue
            key = _normalize_sentence(sentence)
            if key in candidates:
                if source_id not in candidates[key]["source_ids"]:
                    candidates[key]["source_ids"].append(source_id)
                continue
            candidates[key] = {
                "text": sentence,
                "topic": topic,
                "suggested_status": _suggest_status(sentence, source_type),
                "status": "UNKNOWN",
                "review_status": "UNREVIEWED",
                "extracted": True,
                "extraction_method": EXTRACTION_METHOD,
                "source_ids": [source_id],
                "reviewed_by": "",
                "reviewed_at": "",
                "include_in_script": False,
            }
            order.append(key)
            kept += 1
    return [candidates[key] for key in order]


def extract_from_discovery(discovery, topic, max_per_source=10):
    """Extract from a ``research.discover()`` result, using only its
    kept ``sources`` list. ``dropped_sources`` are never extracted
    from -- a source that failed relevance filtering cannot yield a
    candidate claim, however quotable its abstract looks."""
    if not isinstance(discovery, dict):
        return []
    return extract_claims(discovery.get("sources") or [], topic,
                          max_per_source=max_per_source)
