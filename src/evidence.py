"""Claim-level evidence ledger and fail-closed human review policy."""
import argparse
import json
import os
import re
from datetime import datetime, timezone

STATUSES = {"KNOWN", "DEBATED", "UNKNOWN"}
PLACEHOLDERS = ("placeholder", "do not publish", "to cite before publishing")


def empty_ledger():
    return {"schema_version": 1, "claims": [], "sources": []}


def load_ledger(path="data/evidence_ledger.json"):
    if not os.path.exists(path):
        return empty_ledger()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("claims", [])
    data.setdefault("sources", [])
    return data


def save_ledger(ledger, path="data/evidence_ledger.json"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=2, ensure_ascii=False)


def _valid_url(url):
    return isinstance(url, str) and url.startswith(("https://", "http://")) and "." in url.split("://", 1)[-1]


def _source_map(ledger):
    return {s.get("source_id"): s for s in ledger.get("sources", []) if s.get("source_id")}


def validate_claim(claim, sources):
    errors = []
    claim_id = claim.get("claim_id") or "unknown"
    text = (claim.get("text") or "").strip()
    if not text:
        errors.append(claim_id + ": claim text is empty")
    status = claim.get("status")
    if status not in STATUSES:
        errors.append(claim_id + ": status must be KNOWN, DEBATED, or UNKNOWN")
    reviewer = (claim.get("reviewed_by") or "").strip()
    reviewed_at = (claim.get("reviewed_at") or "").strip()
    if not reviewer or not reviewed_at:
        errors.append(claim_id + ": human reviewer and reviewed_at are required")
    else:
        try:
            datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append(claim_id + ": reviewed_at must be ISO-8601")
    ids = claim.get("source_ids") or []
    if status in ("KNOWN", "DEBATED") and not ids:
        errors.append(claim_id + ": KNOWN/DEBATED claims require linked sources")
    for source_id in ids:
        source = sources.get(source_id)
        if not source:
            errors.append(claim_id + ": missing source " + str(source_id))
            continue
        if source.get("review_status") != "APPROVED":
            errors.append(claim_id + ": source " + str(source_id) + " is not human-approved")
        if not (source.get("title") or "").strip():
            errors.append(claim_id + ": source " + str(source_id) + " has no title")
        if not _valid_url(source.get("url", "")):
            errors.append(claim_id + ": source " + str(source_id) + " has no valid public URL")
        if any(p in (source.get("title", "") + " " + source.get("notes", "")).lower() for p in PLACEHOLDERS):
            errors.append(claim_id + ": placeholder source text is not acceptable")
    if status == "DEBATED" and not (claim.get("debate_summary") or "").strip():
        errors.append(claim_id + ": DEBATED claims require a neutral summary of the disagreement")
    return errors


def validate_ledger(ledger):
    sources = _source_map(ledger)
    errors = []
    seen = set()
    for claim in ledger.get("claims", []):
        cid = claim.get("claim_id")
        if not cid or cid in seen:
            errors.append("claim_id is missing or duplicated: " + str(cid))
        seen.add(cid)
        errors.extend(validate_claim(claim, sources))
    return errors


def reviewed_claims(ledger):
    errors = validate_ledger(ledger)
    if errors:
        raise ValueError("Evidence ledger is not publishable:\n- " + "\n- ".join(errors))
    return ledger.get("claims", [])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="data/evidence_ledger.json")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--init", action="store_true")
    args = parser.parse_args(argv)
    if args.init and not os.path.exists(args.ledger):
        save_ledger(empty_ledger(), args.ledger)
    ledger = load_ledger(args.ledger)
    errors = validate_ledger(ledger)
    print("Evidence ledger: {} claim(s), {} source(s).".format(len(ledger["claims"]), len(ledger["sources"])))
    if errors:
        print("BLOCKED:\n- " + "\n- ".join(errors))
        return 1
    print("PASS: every claim has required human review and supporting source records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
