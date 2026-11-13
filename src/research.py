"""Discover scholarly historical sources through free OpenAlex and Crossref APIs.

Discovery is deliberately separate from verification: search results are candidates,
never evidence that a particular claim is true.
"""
import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request

try:
    from src.relevance import DEFAULT_THRESHOLD, filter_sources
    from src.source_types import classify_source
except ImportError:  # pragma: no cover - direct module execution
    from relevance import DEFAULT_THRESHOLD, filter_sources
    from source_types import classify_source

OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"


def normalize_doi(doi):
    """Canonical bare DOI: strip any doi.org URL prefix, lowercase, trim.

    OpenAlex returns DOIs as full URLs (https://doi.org/10.1038/...)
    while Crossref returns them bare (10.1038/...). Without this,
    the same paper survives dedup as two sources.
    """
    if not doi:
        return ""
    value = str(doi).strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    return value.strip().strip("/")


def normalize_title(title):
    """Canonical title for dedup: lowercase, punctuation and extra
    whitespace collapsed."""
    value = re.sub(r"[^a-z0-9]+", " ", (title or "").lower())
    return re.sub(r"\s+", " ", value).strip()


def dedup_key(item):
    """Identity of a discovered source: normalized DOI first, then
    normalized title, then URL. A DOI-less record falls back to its
    title so the same catalogue entry from two providers still merges.
    """
    doi = normalize_doi(item.get("doi"))
    if doi:
        return "doi:" + doi
    title = normalize_title(item.get("title"))
    if title:
        return "title:" + title
    url = (item.get("url") or "").strip().lower()
    return "url:" + url if url else ""


def assign_source_type(item):
    """Backward-compatible alias for the canonical Phase A classifier."""
    return classify_source(item)


def _get_json(url, timeout=20):
    request = urllib.request.Request(url, headers={"User-Agent": "DeepScanResearch/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def search_openalex(query, per_page=10):
    params = urllib.parse.urlencode({"search": query, "per-page": min(max(int(per_page), 1), 50),
                                     "select": "id,doi,title,publication_year,type,authorships,primary_location,locations,abstract_inverted_index"})
    payload = _get_json(OPENALEX + "?" + params)
    results = []
    for item in payload.get("results", []):
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        authors = [a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])]
        results.append({
            "provider": "OpenAlex", "title": item.get("title") or "",
            "url": (location.get("landing_page_url") or item.get("doi") or item.get("id") or ""),
            "doi": item.get("doi"), "publication_year": item.get("publication_year"),
            "publication": source.get("display_name") or "",
            "authors": authors, "work_type": item.get("type") or "",
            "abstract_inverted_index": item.get("abstract_inverted_index"),
            "discovery_only": True,
        })
    return results


def search_crossref(query, rows=10):
    params = urllib.parse.urlencode({"query.bibliographic": query, "rows": min(max(int(rows), 1), 50)})
    payload = _get_json(CROSSREF + "?" + params)
    results = []
    for item in payload.get("message", {}).get("items", []):
        title = (item.get("title") or [""])[0]
        doi = item.get("DOI")
        results.append({
            "provider": "Crossref", "title": title,
            "url": ("https://doi.org/" + doi) if doi else "",
            "doi": doi, "publication_year": (item.get("published-print") or item.get("published-online") or {}).get("date-parts", [[None]])[0][0],
            "publication": (item.get("container-title") or [""])[0],
            "authors": [(" ".join(filter(None, [a.get("given"), a.get("family")]))).strip()
                        for a in item.get("author", [])],
            "work_type": item.get("type") or "", "discovery_only": True,
        })
    return results


def search_library_of_congress(query, limit=10):
    """Search Library of Congress public catalogue API for primary-source leads."""
    params = urllib.parse.urlencode({"fo": "json", "q": query, "c": min(max(int(limit), 1), 50)})
    payload = _get_json("https://www.loc.gov/search/?" + params)
    results = []
    for item in payload.get("results", []):
        results.append({
            "provider": "Library of Congress", "title": item.get("title") or "",
            "url": item.get("url") or "", "doi": None,
            "publication_year": item.get("date") or None,
            "publication": "Library of Congress catalogue",
            "authors": item.get("contributor") or [],
            "work_type": item.get("original_format") or "primary-source catalogue record",
            "discovery_only": True,
        })
    return results


def search_internet_archive(query, limit=10):
    """Search Internet Archive metadata for archival and primary-source leads."""
    params = urllib.parse.urlencode({
        "q": query, "fl[]": ["identifier", "title", "date", "creator", "mediatype"],
        "rows": min(max(int(limit), 1), 50), "output": "json"
    }, doseq=True)
    payload = _get_json("https://archive.org/advancedsearch.php?" + params)
    docs = payload.get("response", {}).get("docs", [])
    results = []
    for item in docs:
        identifier = item.get("identifier")
        results.append({
            "provider": "Internet Archive", "title": item.get("title") or "",
            "url": ("https://archive.org/details/" + identifier) if identifier else "",
            "doi": None, "publication_year": item.get("date") or None,
            "publication": "Internet Archive digital collection",
            "authors": item.get("creator") or [],
            "work_type": item.get("mediatype") or "archival catalogue record",
            "discovery_only": True,
        })
    return results


def discover(query, limit=10):
    """Return deduplicated scholarly candidates; no candidate is auto-approved."""
    found = []
    errors = []
    for provider in (search_openalex, search_crossref, search_library_of_congress, search_internet_archive):
        try:
            found.extend(provider(query, limit))
        except Exception as exc:
            errors.append({"provider": provider.__name__, "error": str(exc)})
    deduped, seen = [], set()
    for item in found:
        key = dedup_key(item)
        if key and key not in seen:
            seen.add(key)
            item["source_id"] = "src_" + str(len(deduped) + 1).zfill(4)
            host = (urllib.parse.urlparse(item.get("url") or "").hostname or "").lower()
            publication = (item.get("publication") or "").lower()
            if any(token in host for token in (".gov", ".edu", "museum", "archive", "library")):
                item["source_priority"] = "institutional_or_primary"
            elif any(token in publication for token in ("journal", "review", "proceedings", "transactions")):
                item["source_priority"] = "academic_publication"
            else:
                item["source_priority"] = "scholarly_candidate"
            item["source_type"] = assign_source_type(item)
            item["notes"] = ""
            item["review_status"] = "UNREVIEWED"
            deduped.append(item)
    priority_order = {"institutional_or_primary": 0, "academic_publication": 1,
                      "scholarly_candidate": 2}
    deduped.sort(key=lambda item: priority_order.get(item.get("source_priority"), 3))
    for index, item in enumerate(deduped, 1):
        item["source_id"] = "src_" + str(index).zfill(4)
    # Relevance triage (never an approval): low-relevance candidates are
    # filtered out but kept in dropped_sources with their reasons, so a
    # reviewer can audit or restore them.
    kept, dropped = filter_sources(deduped, query, threshold=DEFAULT_THRESHOLD)
    return {"query": query, "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sources": kept, "dropped_sources": dropped, "errors": errors,
            "relevance_threshold": DEFAULT_THRESHOLD,
            "warning": "Discovery results are leads, not verified evidence. Human review is required."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", default="data/research_sources.json")
    args = parser.parse_args(argv)
    result = discover(args.query, args.limit)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    # Add discovered records to the working ledger as UNREVIEWED leads.
    # Existing human decisions are preserved and never overwritten.
    try:
        from src.evidence import load_ledger, save_ledger
    except ImportError:
        from evidence import load_ledger, save_ledger
    ledger = load_ledger("data/evidence_ledger.json")
    known = {s.get("url") or s.get("doi") for s in ledger.get("sources", [])}
    used_ids = {s.get("source_id") for s in ledger.get("sources", [])}
    for source in result["sources"]:
        key = source.get("url") or source.get("doi")
        if key and key not in known:
            base_id = source["source_id"]
            source_id = base_id
            suffix = 2
            while source_id in used_ids:
                source_id = base_id + "_" + str(suffix)
                suffix += 1
            ledger["sources"].append({
                "source_id": source_id, "title": source["title"],
                "url": source["url"], "doi": source.get("doi"),
                "publication": source.get("publication", ""),
                "publication_year": source.get("publication_year"),
                "authors": source.get("authors", []), "provider": source.get("provider"),
                "notes": "", "source_priority": source.get("source_priority"),
                "source_type": source.get("source_type"),
                "review_status": "UNREVIEWED"
            })
            known.add(key)
            used_ids.add(source_id)
    save_ledger(ledger, "data/evidence_ledger.json")
    # Keep discovery export IDs aligned with the canonical ledger IDs,
    # including when a prior source already occupied the generated ID.
    ledger_by_key = {(item.get("url") or item.get("doi")): item
                     for item in ledger.get("sources", [])}
    for item in result["sources"]:
        canonical = ledger_by_key.get(item.get("url") or item.get("doi"))
        if canonical:
            item["source_id"] = canonical.get("source_id")
            item["review_status"] = canonical.get("review_status", "UNREVIEWED")
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    print("Discovered {} candidate source(s); none were auto-approved.".format(len(result["sources"])))
    if not result["sources"] and result["errors"]:
        print(json.dumps(result["errors"], indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
