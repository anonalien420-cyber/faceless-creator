"""Deterministic relevance scoring for discovered sources (stdlib only).

Scoring is a triage aid for human reviewers: it ranks discovery
candidates and filters out the clearly irrelevant ones. It never
approves a source or a claim, and every dropped candidate is kept in
the discover() output (``dropped_sources``) so a reviewer can audit
or restore it. Human review stays the only approval path.
"""
import html
import re
from datetime import date

# Proposed default threshold. Owner confirmation is still pending;
# until the owner confirms, treat 40 as provisional, not policy.
DEFAULT_THRESHOLD = 40

# Weight of each canonical source type in the relevance score (max 25).
# "primary" and "official_record" are reserved for human classification
# during review; discovery never assigns them (see src/research.py).
SOURCE_TYPE_WEIGHTS = {
    "primary": 25,
    "archival": 25,
    "official_record": 25,
    "academic": 20,
    "institutional": 15,
    "other": 5,
}

# Component ceilings: term overlap 60 + source-type weight 25 + date 15.
_TERM_MAX = 60
_DATE_MAX = 15

_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "for", "and", "or", "to", "with",
    "by", "from", "at", "is", "are", "was", "were", "it", "its", "as",
    "into", "over", "under", "after", "before", "between", "through",
    "during", "about", "against", "within", "without", "upon", "per",
    "via", "de", "la", "le", "et", "und", "der", "die", "das",
}

# These words describe the channel's broad niche, not the subject of an
# individual episode. They must never be allowed to make an unrelated
# result look relevant (e.g. "History and mysteries" in a physics paper).
_GENERIC_TOPIC_TERMS = {
    "history", "histories", "mystery", "mysteries", "investigated",
    "investigation", "investigations", "modern", "tech", "technology",
    "unsolved", "unexplained",
}

_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")


def _tokens(text):
    """Lowercase content tokens with stopwords removed."""
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower())
            if t and t not in _STOPWORDS]


def abstract_text(source):
    """Return a provider abstract, rebuilding OpenAlex inverted indexes when needed."""
    plain = source.get("abstract") or source.get("snippet") or source.get("description")
    if isinstance(plain, (list, tuple)):
        plain = " ".join(str(part) for part in plain)
    if isinstance(plain, str) and plain.strip():
        plain = html.unescape(re.sub(r"<[^>]+>", " ", plain))
        return re.sub(r"\s+", " ", plain).strip()
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


def _publication_year(source):
    """Extract a 4-digit publication year, or None when unparseable."""
    value = source.get("publication_year")
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = _YEAR_RE.search(str(value))
    return int(match.group(1)) if match else None


def score_source(source, query):
    """Score one discovered source against a query.

    Returns {"score": int|None, "reasons": [str], "scorable": bool,
    "components": {...}}. A source with no title or no provider cannot
    be scored reliably (relevance weights depend on provider-derived
    source_type), so it is marked unscorable and returned with
    score None: callers must keep it for human review rather than
    auto-dropping it. Absence of evidence is never treated as
    evidence of irrelevance.
    """
    title = (source.get("title") or "").strip()
    provider = (source.get("provider") or "").strip()
    if not title or not provider:
        return {"score": None,
                "reasons": ["insufficient_metadata_for_relevance_scoring"],
                "scorable": False, "components": {}}
    reasons = []
    components = {}

    # 1. Query-term overlap with title (full credit) and abstract
    #    (half credit), out of _TERM_MAX.
    # Score against episode-specific terms only. Generic channel-niche words
    # such as "history" and "mystery" are deliberately excluded.
    query_terms = [term for term in _tokens(query)
                   if term not in _GENERIC_TOPIC_TERMS]
    title_tokens = set(_tokens(title))
    abstract_tokens = set(_tokens(abstract_text(source)))
    if query_terms:
        credit = 0.0
        for term in query_terms:
            if term in title_tokens:
                credit += 1.0
            elif term in abstract_tokens:
                credit += 0.5
        term_score = int(round(_TERM_MAX * credit / len(query_terms)))
        if credit == 0:
            reasons.append("no_topic_anchor_match")
    else:
        # A broad niche query is not a usable evidence-search topic.
        term_score = 0
        reasons.append("query_has_no_specific_topic_terms")
    components["term_overlap"] = term_score
    if term_score < _TERM_MAX // 2:
        reasons.append("low_term_overlap")
    if not abstract_tokens:
        reasons.append("no_abstract_available")

    # 2. Source-type weight.
    source_type = (source.get("source_type") or "other").lower()
    type_score = SOURCE_TYPE_WEIGHTS.get(source_type, SOURCE_TYPE_WEIGHTS["other"])
    components["source_type"] = type_score
    if source_type not in SOURCE_TYPE_WEIGHTS or source_type == "other":
        reasons.append("source_type_other")

    # 3. Date sanity: a plausible, non-future publication year.
    year = _publication_year(source)
    current_year = date.today().year
    if year is None:
        date_score = 5
        reasons.append("missing_publication_year")
    elif year > current_year:
        date_score = 0
        reasons.append("future_publication_year")
    elif year < 1000:
        date_score = 5
        reasons.append("implausible_publication_year")
    else:
        date_score = _DATE_MAX
    components["date_sanity"] = date_score

    return {"score": term_score + type_score + date_score,
            "reasons": reasons, "scorable": True, "components": components}


def filter_sources(sources, query, threshold=DEFAULT_THRESHOLD):
    """Split candidates into (kept, dropped) at the threshold.

    Kept sources are annotated in place with "relevance_score" and
    "relevance_reasons". Dropped entries are returned as
    {"source": ..., "relevance_score": ..., "reasons": [...]} records
    for reviewer audit; nothing is discarded silently. Unscorable
    sources are always kept (score None) for human review.
    """
    kept, dropped = [], []
    for source in sources:
        result = score_source(source, query)
        source["relevance_score"] = result["score"]
        source["relevance_reasons"] = result["reasons"]
        hard_reject = any(reason in result["reasons"] for reason in (
            "no_topic_anchor_match", "query_has_no_specific_topic_terms"
        ))
        if not result["scorable"] or (not hard_reject and result["score"] >= threshold):
            kept.append(source)
        else:
            dropped.append({"source": source,
                            "relevance_score": result["score"],
                            "reasons": result["reasons"]})
    return kept, dropped
