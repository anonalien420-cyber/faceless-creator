"""Lightweight lexical similarity for topic dedupe (stdlib, $0, offline).

Exact-match topic memory misses paraphrases: "Lost city of Atlantis" and
"Atlantis forgotten ruins lost city" are the same story. This module
scores topic similarity with smooth TF-IDF cosine over content words
(stopwords removed, crude stemming), so near-duplicate topics worded
differently are skipped.

Design choice — precision over recall. The dedupe guard SKIPS a candidate
topic, so a false merge (treating "lost city of Petra" as a repeat of
"lost city of Atlantis") would silently drop genuinely new content. The
smooth TF-IDF cosine leans conservative: it rewards sharing distinctive
content words and is tuned (default threshold 0.6) to catch clear
paraphrases and exact repeats while keeping distinct entities apart.

Known limitation: purely lexical, so true synonyms with no shared word
("built" vs "construction") are NOT caught. That is acceptable for a $0
offline guard; an embedding model would catch them but would break the
no-download/no-network default. The threshold is config-tunable
(topic_similarity_threshold).

No embeddings, no model download, no network.
"""

from __future__ import annotations

import math
import re
from collections import Counter

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "was", "were", "are", "be", "been", "it", "its", "this", "that",
    "how", "why", "what", "who", "when", "where", "did", "does", "do",
    "you", "your", "we", "our", "they", "their", "he", "she", "his", "her",
    "s", "t", "as", "at", "by", "from", "about", "into", "still", "ever",
    "never", "most", "more", "than", "then", "so", "such", "can", "could",
}


def _stem(word):
    """Crude suffix stripping so 'ruins'/'ruined' and 'cities'/'city'
    land close together. Not a full stemmer — good enough for dedupe."""
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if suffix == "ies":
                return word[:-3] + "y"
            return word[: -len(suffix)]
    return word


def tokenize(text):
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [_stem(w) for w in words if w not in STOPWORDS and len(w) > 2]


def _tf(tokens):
    counts = Counter(tokens)
    total = max(1, len(tokens))
    return {t: c / total for t, c in counts.items()}


def similarity(topic_a, topic_b, corpus=None):
    """TF-IDF cosine similarity of two topics in [0, 1].

    `corpus` is an optional list of other topic strings used to compute
    IDF (rare words weigh more). With no corpus, IDF is computed over the
    two topics alone, which still downweights shared generic words."""
    ta, tb = tokenize(topic_a), tokenize(topic_b)
    if not ta or not tb:
        return 0.0
    docs = [ta, tb] + [tokenize(t) for t in (corpus or [])]
    n = len(docs)
    df = Counter()
    for doc in docs:
        df.update(set(doc))
    # Smooth IDF with a +1 floor (sklearn-style): log((N+1)/(df+1)) + 1.
    # The floor matters for short topic strings — without it, words shared
    # by the two topics collapse to ~0 weight in a tiny corpus and the
    # similarity signal disappears. The floor keeps shared content words
    # meaningful while still letting rare words weigh a little more.
    idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    va = {t: w * idf.get(t, 0) for t, w in _tf(ta).items()}
    vb = {t: w * idf.get(t, 0) for t, w in _tf(tb).items()}
    dot = sum(va.get(t, 0) * w for t, w in vb.items())
    na = math.sqrt(sum(w * w for w in va.values()))
    nb = math.sqrt(sum(w * w for w in vb.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def is_similar_topic(topic, history_topics, threshold=0.6):
    """True when `topic` is a near-duplicate of any historical topic.

    Returns (bool, matched_topic, score). Pure function; callers decide
    what to do (script.py skips the candidate)."""
    best, best_score = "", 0.0
    others = [t for t in history_topics if t]
    for other in others:
        score = similarity(topic, other, corpus=others)
        if score > best_score:
            best, best_score = other, score
    return best_score >= threshold, best, round(best_score, 3)
