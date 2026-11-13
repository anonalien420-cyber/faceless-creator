"""Canonical source-type taxonomy for Deep Scan evidence records.

Classification is deterministic metadata, not an assessment of truth.
"""
from urllib.parse import urlparse

SOURCE_TYPES = {
    "primary",
    "archival",
    "official_record",
    "academic",
    "institutional",
    "other",
}


def classify_source(source):
    """Classify a discovery record using explicit metadata and conservative rules."""
    source = source or {}
    explicit = str(source.get("source_type") or "").strip().lower()
    if explicit in SOURCE_TYPES:
        return explicit
    # The former broad "secondary" label does not prove peer review.
    if explicit == "secondary":
        return "other"

    provider = str(source.get("provider") or "").strip().lower()
    work_type = str(source.get("work_type") or "").strip().lower()
    publication = str(source.get("publication") or "").strip().lower()
    url = str(source.get("url") or "")
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        host = ""

    if provider in {"library of congress", "internet archive"}:
        return "archival"
    if any(token in work_type for token in (
        "primary document", "excavation report", "laboratory analysis",
        "lab analysis", "original record",
    )):
        return "primary"
    if host.endswith(".gov") or ".gov." in host:
        return "official_record"
    if any(token in host for token in ("archive.org", "archives.", "library.", "museum.")):
        return "archival"
    if provider in {"openalex", "crossref"} and (
        publication or work_type in {"article", "journal-article", "proceedings-article"}
    ):
        return "academic"
    priority = str(source.get("source_priority") or "").strip().lower()
    if priority == "institutional_or_primary":
        return "institutional"
    if priority == "academic_publication":
        return "academic"
    if host.endswith(".edu") or ".edu." in host or any(
        token in host for token in ("museum", "university", "institute")
    ):
        return "institutional"
    return "other"
