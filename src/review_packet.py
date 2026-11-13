"""Build a human-readable evidence review packet from discovery-only sources.

This module never approves sources or invents historical claims. It creates
an editable checklist so a reviewer can inspect source records and write
precise claims before editing the canonical evidence ledger.
"""
import argparse
import json
import os
from datetime import datetime, timezone

from src.claim_extraction import extract_claims


def build_packet(research, ledger, topic, extracted_claims=None):
    sources = research.get("sources", [])
    if extracted_claims is None:
        extracted_claims = extract_claims(sources, research.get("expanded_query") or topic)
    existing = {s.get("source_id"): s for s in ledger.get("sources", [])}
    rows = []
    for source in sources:
        source_id = source.get("source_id", "")
        canonical = existing.get(source_id, {})
        rows.append({
            "source_id": source_id,
            "title": source.get("title", ""),
            "url": source.get("url", ""),
            "publication": source.get("publication", ""),
            "publication_year": source.get("publication_year"),
            "authors": source.get("authors", []),
            "provider": source.get("provider", ""),
            "source_type": source.get("source_type", "other"),
            "relevance_score": source.get("relevance_score"),
            "relevance_reasons": source.get("relevance_reasons", []),
            "review_status": canonical.get("review_status", source.get("review_status", "UNREVIEWED")),
            "review_notes": canonical.get("notes", ""),
            "review_decision": "PENDING",
        })
    return {
        "schema_version": 1,
        "topic": topic,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "discovery_warning": research.get("warning", "Discovery candidates are not verified evidence."),
        "relevance_threshold": research.get("relevance_threshold", 40),
        "sources": rows,
        "dropped_sources": research.get("dropped_sources", []),
        "extracted_claims": extracted_claims,
        "claim_review_template": {
            "claim_id": "",
            "topic": topic,
            "text": "",
            "status": "UNKNOWN",
            "source_ids": [],
            "reviewed_by": "",
            "reviewed_at": "",
            "include_in_script": False,
            "reviewer_notes": "Write one precise, checkable statement. Do not infer facts from a source title or search snippet."
        }
    }


def render_markdown(packet):
    lines = [
        "# Deep Scan evidence review packet",
        "",
        f"**Episode topic:** {packet['topic']}",
        f"**Generated:** {packet['generated_at']}",
        f"**Relevance triage threshold:** {packet.get('relevance_threshold', 40)} (ranking aid only)",
        "",
        "> Discovery results are leads, not verified evidence. No source or claim in this packet is approved.",
        "",
        "## Reviewer checklist",
        "",
        "1. Open the original source URL and confirm it resolves to the cited record.",
        "2. Read the relevant passage or inspect the original archival object, not just the search result.",
        "3. Record the exact page, section, catalogue number, or timestamp in your notes.",
        "4. Decide whether the source directly supports a precise claim. Mark each source APPROVED or REJECTED only after inspection.",
        "5. Add claim records to data/evidence_ledger.json; each claim must link to approved source IDs and include reviewer identity and ISO-8601 review time.",
        "6. Label unresolved or conflicting interpretations DEBATED and summarize both positions. Use UNKNOWN when evidence is insufficient.",
        "",
        "## Discovered source candidates",
        ""
    ]
    for source in packet["sources"]:
        lines.extend([
            f"### {source['source_id']} · {source['title'] or '(untitled record)'}",
            f"- URL: {source['url'] or '(no URL returned)'}",
            f"- Publication: {source['publication'] or 'Not supplied'}",
            f"- Year: {source['publication_year'] or 'Not supplied'}",
            f"- Authors/contributors: {', '.join(source['authors']) if source['authors'] else 'Not supplied'}",
            f"- Discovery provider: {source['provider'] or 'Not supplied'}",
            f"- Canonical source type: {source['source_type']}",
            f"- Relevance score: {source['relevance_score'] if source['relevance_score'] is not None else 'Not scorable; human review required'}",
            f"- Relevance reasons: {', '.join(source['relevance_reasons']) or 'No flags'}",
            f"- Current ledger status: {source['review_status']}",
            "- Reviewer decision: PENDING",
            "- Review notes (exact passage/page/catalogue reference and relevance):",
            "",
        ])
    if packet.get("dropped_sources"):
        lines.extend([
            "## Filtered-out discovery candidates (audit trail)",
            "",
            "These candidates did not pass the configured discovery filters. They remain visible for audit and are not silently discarded.",
            "",
        ])
        for dropped in packet["dropped_sources"]:
            source = dropped.get("source", dropped)
            lines.extend([
                "- {} — {}".format(source.get("title", "(untitled)"),
                                   dropped.get("reason") or ", ".join(dropped.get("reasons", [])) or "below threshold"),
                "  - Relevance score: {}".format(dropped.get("relevance_score", "not scored")),
                "  - Source ID: {}".format(source.get("source_id", "unknown")),
                "",
            ])
    lines.extend([
        "## Extracted candidate claims (UNREVIEWED)",
        "",
        "These are verbatim source sentences offered for reviewer triage only. They are not ledger claims and cannot enter a script.",
        "",
    ])
    for claim in packet.get("extracted_claims", []):
        lines.extend([
            "- Candidate: {}".format(claim.get("claim_id")),
            "  - Text: {}".format(claim.get("text")),
            "  - Source IDs: {}".format(", ".join(claim.get("source_ids", []))),
            "  - Suggested tier: {}".format(claim.get("suggested_status", "UNKNOWN")),
            "  - Final tier: UNKNOWN (human decision required)",
            "  - Include in script: false",
            "  - Extraction: {}".format(claim.get("extraction_method")),
            "",
        ])
    lines.extend([
        "## Claim worksheet",
        "",
        "Do not copy a source title into the claim field. Write one factual, checkable sentence per claim.",
        "",
        "- Claim ID:",
        "- Exact topic:",
        "- Claim text:",
        "- Status: KNOWN / DEBATED / UNKNOWN",
        "- Supporting approved source IDs:",
        "- Reviewer:",
        "- Reviewed at (ISO-8601):",
        "- Notes, quotation/page reference, caveats, and contradictions:",
        "",
        "## Safety gate",
        "",
        "This packet is not an evidence ledger and does not unblock production. The production gate remains closed until the canonical ledger contains human-reviewed claims linked to human-approved source records. Never mark a source APPROVED based only on this packet.",
        ""
    ])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/research_sources.json")
    parser.add_argument("--ledger", default="data/evidence_ledger.json")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--output", default="data/review_packet.md")
    parser.add_argument("--json-output", default="data/review_packet.json")
    args = parser.parse_args(argv)
    with open(args.input, encoding="utf-8") as fh:
        research = json.load(fh)
    with open(args.ledger, encoding="utf-8") as fh:
        ledger = json.load(fh)
    packet = build_packet(research, ledger, args.topic)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(packet))
    with open(args.json_output, "w", encoding="utf-8") as fh:
        json.dump(packet, fh, indent=2, ensure_ascii=False)
    print("Wrote evidence review packet with {} candidate(s): {}".format(
        len(packet["sources"]), args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
