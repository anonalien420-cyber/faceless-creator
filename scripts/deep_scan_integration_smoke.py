"""Credential-free end-to-end Deep Scan smoke test using synthetic evidence/media."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.claim_extraction import extract_claims
from src.relevance import filter_sources
from src.review_packet import build_packet
from src.documentary import build_documentary
from src.evidence import save_ledger, validate_ledger
from src.growth import lint_metadata
from src.qa import run_qa
from src.seo import build_entry
from src.video import build_video


def synthetic_ledger():
    sources = [
        {"source_id": "archive", "title": "Synthetic archive catalogue entry",
         "url": "https://archive.example.org/record", "publication": "Synthetic archive",
         "publication_year": 1901, "review_status": "APPROVED",
         "source_type": "primary", "notes": "Synthetic fixture for automated tests."},
        {"source_id": "journal", "title": "Synthetic historical research paper",
         "url": "https://journal.example.com/research", "publication": "Synthetic journal",
         "publication_year": 2020, "review_status": "APPROVED",
         "source_type": "academic", "notes": "Synthetic fixture for automated tests."},
    ]
    statement = ("A documented historical record describes the event with a precise date, named location, "
                 "and surviving material evidence that researchers can examine, rather than relying on later "
                 "legends or unsupported retellings preserved in the original surviving archive.")
    claims = []
    for index in range(4):
        claims.append({
            "claim_id": "fixture-{}".format(index + 1), "topic": "Synthetic history test",
            "text": statement, "status": "KNOWN", "source_ids": ["archive", "journal"],
            "reviewed_by": "automated-test-fixture", "reviewed_at": "2026-11-09T00:00:00Z",
            "shock_hook": index == 0, "sequence": index + 1,
        })
    return {"schema_version": 1, "claims": claims, "sources": sources}


def main():
    # Exercise the research triage and extraction path before documentary
    # generation. The candidate is deliberately synthetic and stays outside
    # the ledger until the fixture reviewer explicitly confirms it.
    research_fixture = [{
        "source_id": "research-smoke-1",
        "title": "Great Pyramid void measurement test record",
        "url": "https://research-smoke.example.org/record",
        "publication": "Synthetic research fixture",
        "publication_year": 2020,
        "source_type": "academic",
        "review_status": "UNREVIEWED",
        "abstract": "Synthetic test fixture: researchers measured a 30 metre void in the Great Pyramid."
    }]
    kept, dropped = filter_sources(research_fixture, "Great Pyramid void", threshold=40)
    if dropped or len(kept) != 1:
        raise RuntimeError("Research relevance smoke failed: {}".format(dropped))
    candidates = extract_claims(kept, "Great Pyramid")
    if len(candidates) != 1 or candidates[0]["text"] not in research_fixture[0]["abstract"]:
        raise RuntimeError("Claim extraction smoke failed: {}".format(candidates))
    packet = build_packet({"sources": kept, "dropped_sources": dropped},
                          {"sources": [], "claims": []}, "Great Pyramid")
    if not packet["extracted_claims"] or packet["extracted_claims"][0]["include_in_script"]:
        raise RuntimeError("Review packet safety smoke failed")

    with tempfile.TemporaryDirectory(prefix="deep-scan-integration-") as temp:
        data_dir = os.path.join(temp, "data")
        os.makedirs(data_dir)
        ledger = synthetic_ledger()
        errors = validate_ledger(ledger)
        if errors:
            raise RuntimeError("Synthetic ledger invalid: " + "; ".join(errors))
        ledger_path = os.path.join(data_dir, "evidence_ledger.json")
        save_ledger(ledger, ledger_path)
        script = build_documentary("Synthetic history test", "short", ledger)
        script_path = os.path.join(temp, "script.json")
        with open(script_path, "w", encoding="utf-8") as fh:
            json.dump(script, fh, indent=2)
        seo = build_entry(script, {"channel_promise": "A synthetic promise for integration tests."}, "short")
        lint = lint_metadata(seo)
        if not lint["passed"]:
            raise RuntimeError("Metadata QA failed: " + "; ".join(lint["errors"]))
        image = os.path.join(temp, "synthetic.png")
        audio = os.path.join(temp, "synthetic.wav")
        video = os.path.join(temp, "deep-scan-integration.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        "color=c=0x202b3a:s=1080x1920:d=8", "-frames:v", "1", image],
                       check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=8", "-c:a", "pcm_s16le", audio],
                       check=True, capture_output=True)
        build_video(script, audio, video, visuals=[{"path": image, "type": "image",
            "width": 1080, "height": 1920}], duration=8, bitrate="2M",
            min_resolution=1080, width=1080, height=1920)
        previous = os.getcwd()
        try:
            os.chdir(temp)
            passed = run_qa(video, narration=audio, script_text=script["text"],
                            title=script["topic"], report_path=os.path.join(data_dir, "qa.json"),
                            fmt="short", script=script)
        finally:
            os.chdir(previous)
        if not passed:
            with open(os.path.join(data_dir, "qa.json"), encoding="utf-8") as fh:
                report = json.load(fh)
            raise RuntimeError("End-to-end QA failed: {}".format(report))
        print("PASS: reviewed evidence -> documentary -> SEO metadata -> 1080x1920 render -> technical and historical QA")


if __name__ == "__main__":
    main()
