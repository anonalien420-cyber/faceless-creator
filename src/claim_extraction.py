"""Conservative, provenance-preserving candidate claim extraction.

Extracted sentences remain unreviewed candidates. This module never writes
claims to the evidence ledger, approves sources, or invents sentence text.
"""
import hashlib
import html
import re

from src.relevance import abstract_text, _tokens


_FACTUAL_PREDICATE = re.compile(
    r"\\b(discovered|detected|measured|observed|identified|confirmed|"
    r"reported|recorded|found|revealed|indicated|located|estimated|"
    r"consists|contains|is situated|was built|were built)\\b",
    re.IGNORECASE,
)
_MEASUREMENT = re.compile(
    r"\\b\\d+(?:[.,]\\d+)?\\s*(?:mm|cm|m|metres?|meters?|km|kilometres?|"
    r"kilometers?|degrees?|years?|percent|%)\\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\\b(?:1[0-9]{3}|20[0-9]{2})\\b")


def _source_abstract(source):
    text = source.get("abstract") or abstract_text(source)
    text = html.unescape(str(text))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\\s+", " ", text).strip()


def _sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\\s+", text) if part.strip()]


def _topic_terms(topic):
    return set(_tokens(topic))


def extract_claims(sources, topic, max_claims_per_source=20):
    """Return candidate sentences copied verbatim from source abstracts only."""
    terms = _topic_terms(topic)
    candidates = []
    by_text = {}
    for source in sources or []:
        source_id = source.get("source_id")
        if not source_id:
            continue
        abstract = _source_abstract(source)
        if not abstract:
            continue
        digest = hashlib.sha256(abstract.encode("utf-8")).hexdigest()
        for sentence_index, sentence in enumerate(_sentences(abstract)):
            sentence_terms = set(_tokens(sentence))
            if not terms.intersection(sentence_terms):
                continue
            if not (_FACTUAL_PREDICATE.search(sentence)
                    or _MEASUREMENT.search(sentence)
                    or _YEAR.search(sentence)):
                continue
            normalized = " ".join(_tokens(sentence))
            if not normalized:
                continue
            if normalized in by_text:
                existing = by_text[normalized]
                if source_id not in existing["source_ids"]:
                    existing["source_ids"].append(source_id)
                continue
            source_type = source.get("source_type", "other")
            supported_tier = (
                "KNOWN" if source_type in ("primary", "academic")
                and (_MEASUREMENT.search(sentence) or _FACTUAL_PREDICATE.search(sentence))
                else "UNKNOWN"
            )
            candidate = {
                "claim_id": "candidate_{:04d}".format(len(candidates) + 1),
                "topic": topic,
                "text": sentence,
                "extracted_text": sentence,
                "source_ids": [source_id],
                "status": "UNKNOWN",
                "suggested_status": supported_tier,
                "review_status": "UNREVIEWED",
                "reviewed_by": "",
                "reviewed_at": "",
                "include_in_script": False,
                "extracted": True,
                "extraction_method": "abstract_sentence",
                "provenance": {
                    "source_title": source.get("title", ""),
                    "source_url": source.get("url", ""),
                    "publication_year": source.get("publication_year"),
                    "sentence_index": sentence_index,
                    "abstract_sha256": digest,
                },
            }
            candidates.append(candidate)
            by_text[normalized] = candidate
            if len(candidates) >= max_claims_per_source * max(1, len(sources or [])):
                return candidates
    return candidates
