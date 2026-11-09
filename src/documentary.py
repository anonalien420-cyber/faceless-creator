"""Evidence-driven Deep Scan script and scene package generator.

No generic historical filler is emitted: every narrated factual statement maps
to a reviewed claim ID. The visual directions are labelled reconstructions.
"""
import argparse
import json
import os

from src.evidence import load_ledger, reviewed_claims


def build_visual_prompts(claim, scene_number):
    period = claim.get("period") or "period not established by reviewed evidence"
    place = claim.get("location") or "location not established by reviewed evidence"
    clothing = claim.get("clothing") or "do not invent clothing details; use neutral silhouettes"
    architecture = claim.get("architecture") or "show only documented architectural features"
    objects = claim.get("objects") or "include only objects explicitly documented in cited sources"
    return {
        "scene": scene_number,
        "claim_ids": [claim["claim_id"]],
        "visual_type": "AI-generated interpretive reconstruction, NOT historical footage",
        "image_prompt": (
            "Historically grounded interpretive reconstruction, clearly illustrative and not archival. "
            "Period: {}. Location: {}. Clothing: {}. Architecture: {}. Objects: {}. "
            "Lighting: restrained documentary chiaroscuro, physically plausible natural light. "
            "Atmosphere: serious, mysterious, evidence-led. Avoid invented insignia, text, symbols, "
            "anachronisms, fantasy elements, or presenting this image as an authentic photograph."
        ).format(period, place, clothing, architecture, objects),
        "animation_prompt": (
            "Slow documentary camera push-in with subtle parallax and restrained environmental motion. "
            "Preserve the depicted period details. Do not add new objects, people, events, or actions "
            "not established by the cited claim. Maintain the label 'AI reconstruction' in production metadata."
        ),
    }


def build_documentary(topic, fmt, ledger):
    claims = reviewed_claims(ledger)
    selected = [c for c in claims if c.get("include_in_script", True)]
    if not selected:
        raise ValueError("No reviewed claims are available for documentary generation.")
    selected.sort(key=lambda c: (c.get("sequence", 9999), c["claim_id"]))
    hook_claim = next((c for c in selected if c.get("status") == "KNOWN" and c.get("shock_hook")), None)
    if not hook_claim:
        raise ValueError("A reviewed KNOWN claim marked shock_hook=true is required; no hook will be invented.")
    sections, scenes, sources, lines = [], [], {}, []
    for i, claim in enumerate(selected, 1):
        evidence_text = claim["text"].strip()
        tier = claim["status"]
        prefix = {"KNOWN": "", "DEBATED": "Researchers disagree about this point: ",
                  "UNKNOWN": "What remains unknown: "}[tier]
        narration = prefix + evidence_text
        if tier == "DEBATED":
            narration += " " + claim["debate_summary"].strip()
        section = {"title": claim.get("section_title") or "Evidence {}".format(i),
                   "tier": tier, "text": narration, "claim_ids": [claim["claim_id"]],
                   "source_ids": claim.get("source_ids", [])}
        sections.append(section)
        if claim["claim_id"] != hook_claim["claim_id"]:
            lines.append(narration)
        scenes.append(build_visual_prompts(claim, i))
        for sid in claim.get("source_ids", []):
            source = next(s for s in ledger["sources"] if s.get("source_id") == sid)
            sources[sid] = {"title": source["title"], "url": source["url"],
                            "publication": source.get("publication", ""),
                            "publication_year": source.get("publication_year"),
                            "notes": source.get("notes", "")}
    hook = hook_claim["text"].strip()
    body = " ".join(lines)
    if fmt == "short":
        body = (hook + " " + body + " " +
                "The evidence establishes some things. Other questions remain open. "
                "Which conclusion is best supported by the record?")
    else:
        body = (hook + " " + body + " " +
                "The record supports what is documented, not every explanation proposed for it. "
                "The unresolved questions remain unresolved until new evidence changes that.")
    return {
        "topic": topic, "format": fmt, "style": "history_mystery",
        "hook": hook, "shock_hook": {"text": hook, "tier": "KNOWN",
            "source": next((sources[sid] for sid in hook_claim.get("source_ids", []) if sid in sources), {})},
        "sections": sections, "chapters": [s["title"] for s in sections],
        "text": body, "cta": "The evidence is what we have. The unanswered questions are what remain. What do you think happened? What does the record actually support?",
        "word_count": len(body.split()), "claim_ids": [c["claim_id"] for c in selected],
        "sources": list(sources.values()), "evidence_ledger_version": ledger.get("schema_version", 1),
        "scenes": scenes, "visual_disclaimer": "All generated visuals are interpretive AI reconstructions, never authentic historical footage."
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--format", choices=["short", "long"], default="short")
    parser.add_argument("--ledger", default="data/evidence_ledger.json")
    parser.add_argument("--output", default="data/documentary_package.json")
    args = parser.parse_args(argv)
    package = build_documentary(args.topic, args.format, load_ledger(args.ledger))
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump([package], fh, indent=2, ensure_ascii=False)
    print("Wrote evidence-backed {} documentary package with {} claims and {} scenes.".format(
        args.format, len(package["claim_ids"]), len(package["scenes"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
