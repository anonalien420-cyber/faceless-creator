"""Best-effort Wayback Machine snapshot lookup for historical source records."""
import argparse
import json
import os
import time
import urllib.parse
import urllib.request


def lookup_snapshot(url, timeout=15):
    endpoint = "https://archive.org/wayback/available?" + urllib.parse.urlencode({"url": url})
    request = urllib.request.Request(endpoint, headers={"User-Agent": "DeepScanSourceArchive/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    snapshot = (payload.get("archived_snapshots") or {}).get("closest") or {}
    return {
        "archive_status": "AVAILABLE" if snapshot.get("url") else "NOT_FOUND",
        "archive_snapshot_url": snapshot.get("url", ""),
        "archive_timestamp": snapshot.get("timestamp", ""),
        "archive_available": bool(snapshot.get("available", False)),
    }


def snapshot_sources(source_file, output_file, timeout=15, pause=1.0):
    with open(source_file, encoding="utf-8") as fh:
        data = json.load(fh)
    sources = data if isinstance(data, list) else data.get("sources", [])
    results, errors = [], []
    for source in sources:
        url = source.get("url", "")
        if not url:
            continue
        try:
            source.update(lookup_snapshot(url, timeout=timeout))
            results.append(source)
        except Exception as exc:
            source["archive_status"] = "LOOKUP_FAILED"
            source["archive_error"] = str(exc)[:500]
            errors.append({"source_id": source.get("source_id"), "error": str(exc)[:500]})
        time.sleep(max(0, pause))
    output = {"source_count": len(sources), "sources": sources, "errors": errors,
              "disclaimer": "Archive availability preserves a historical copy link; it does not validate source authenticity or claim truth."}
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/research_sources.json")
    parser.add_argument("--output", default="data/research_sources_archived.json")
    args = parser.parse_args(argv)
    result = snapshot_sources(args.input, args.output)
    print("Wayback snapshot lookup: {} source(s), {} lookup error(s)".format(
        result["source_count"], len(result["errors"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
