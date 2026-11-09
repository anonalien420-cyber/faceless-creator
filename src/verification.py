"""Historical evidence verification. Scores metadata completeness, never truth.

A human remains responsible for approving sources and claims. This module
checks source diversity, provenance metadata, date consistency, and explicit
contradiction links without silently upgrading any claim's evidence tier.
"""
from datetime import date, datetime
from urllib.parse import urlparse


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _host(url):
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except (TypeError, ValueError):
        return ""


def verify_ledger(ledger):
    claims = ledger.get("claims", [])
    sources = {s.get("source_id"): s for s in ledger.get("sources", [])
               if s.get("source_id")}
    claim_map = {c.get("claim_id"): c for c in claims if c.get("claim_id")}
    results = []
    for claim in claims:
        cid = claim.get("claim_id") or "unknown"
        linked = [sources[sid] for sid in claim.get("source_ids", [])
                  if sid in sources]
        hosts = {_host(s.get("url")) for s in linked if _host(s.get("url"))}
        primary = [s for s in linked if s.get("source_type") in
                   ("primary", "archival", "official_record")]
        errors, warnings = [], []
        start = _parse_date(claim.get("date_start"))
        end = _parse_date(claim.get("date_end"))
        if claim.get("date_start") and not start:
            errors.append("date_start must begin with a valid ISO date")
        if claim.get("date_end") and not end:
            errors.append("date_end must begin with a valid ISO date")
        if start and end and start > end:
            errors.append("date_start occurs after date_end")
        if claim.get("status") == "KNOWN" and len(linked) < 1:
            errors.append("KNOWN claim has no linked source records")
        if claim.get("status") == "KNOWN" and len(hosts) < 2:
            warnings.append("KNOWN claim has fewer than two independent source domains")
        if claim.get("status") == "DEBATED" and len(hosts) < 2:
            errors.append("DEBATED claim needs sources from at least two domains")
        if claim.get("status") == "KNOWN" and not primary:
            warnings.append("No source is explicitly classified as primary/archival/official")
        if not linked:
            warnings.append("No linked source records")
        for other_id in claim.get("conflicts_with", []):
            if other_id not in claim_map:
                errors.append("conflicts_with references missing claim " + str(other_id))
            elif other_id == cid:
                errors.append("claim cannot conflict with itself")
        # Metadata score is not a probability that the claim is true.
        score = 0
        score += 25 if linked else 0
        score += 20 if len(hosts) >= 2 else (10 if hosts else 0)
        score += 20 if primary else 0
        score += 15 if all(s.get("review_status") == "APPROVED" for s in linked) and linked else 0
        score += 10 if all(s.get("notes") for s in linked) and linked else 0
        score += 10 if start or end or claim.get("date_precision") == "not_applicable" else 0
        results.append({
            "claim_id": cid, "status": claim.get("status"),
            "metadata_completeness_score": score,
            "score_disclaimer": "Completeness indicator only; not a truth probability or automated fact-check.",
            "source_count": len(linked), "independent_domains": sorted(hosts),
            "primary_source_count": len(primary), "errors": errors, "warnings": warnings,
            "conflicts_with": claim.get("conflicts_with", []),
            "passed": not errors,
        })
    return {
        "schema_version": 1,
        "claim_count": len(results),
        "passed": all(r["passed"] for r in results),
        "claims": results,
        "policy": "No automated score approves a source or changes KNOWN/DEBATED/UNKNOWN status.",
    }


def write_report(ledger, output_path):
    import json
    report = verify_ledger(ledger)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    return report


if __name__ == "__main__":
    import argparse
    from src.evidence import load_ledger
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="data/evidence_ledger.json")
    parser.add_argument("--output", default="data/verification_report.json")
    args = parser.parse_args()
    result = write_report(load_ledger(args.ledger), args.output)
    print("Historical verification metadata report: {} claim(s), {}".format(
        result["claim_count"], "PASS" if result["passed"] else "BLOCKED"))
    raise SystemExit(0 if result["passed"] else 1)
