"""Discover scholarly historical sources through free OpenAlex and Crossref APIs.

Discovery is deliberately separate from verification: search results are candidates,
never evidence that a particular claim is true.
"""
import argparse
import json
import os
import time
import urllib.parse
import urllib.request

OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"


def _get_json(url, timeout=20):
    request = urllib.request.Request(url, headers={"User-Agent": "DeepScanResearch/1.0 (mailto:research@example.org)"})
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


def discover(query, limit=10):
    """Return deduplicated scholarly candidates; no candidate is auto-approved."""
    found = []
    errors = []
    for provider in (search_openalex, search_crossref):
        try:
            found.extend(provider(query, limit))
        except Exception as exc:
            errors.append({"provider": provider.__name__, "error": str(exc)})
    deduped, seen = [], set()
    for item in found:
        key = (item.get("doi") or item.get("url") or item.get("title", "")).lower()
        if key and key not in seen:
            seen.add(key)
            item["source_id"] = "src_" + str(len(deduped) + 1).zfill(4)
            item["notes"] = ""
            item["review_status"] = "UNREVIEWED"
            deduped.append(item)
    return {"query": query, "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sources": deduped, "errors": errors,
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
    print("Discovered {} candidate source(s); none were auto-approved.".format(len(result["sources"])))
    if not result["sources"] and result["errors"]:
        print(json.dumps(result["errors"], indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
