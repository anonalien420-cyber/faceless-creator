"""QA gate: check every rendered MP4 with ffprobe/ffmpeg BEFORE upload.

Checks (all local, no API):
1. file exists and is non-empty
2. duration matches narration within tolerance (default 2.0s)
3. audio stream present and not silent (volumedetect)
4. no long black/silent stretches (blackdetect / silencedetect, >2s)
5. resolution is 1080x1920
6. frame rate 30fps (within 0.5fps)
7. captions file present and non-empty (<video>.ass next to the MP4)
8. title card present: the first 3 seconds are not black
9. audio not clipping badly (max_volume above -0.5 dB)

Auto-fixes (logged, one retry only):
- too quiet audio -> re-mux with a volume gain
- clipping audio -> re-mux with a volume cut
- missing/low-res visual or long black stretch -> re-render with the
  fallback animated gradient (via src.video build_video)
- empty/missing captions -> re-render (captions are burned in at render)

If a fix fails, or any check still fails after ONE retry, QA FAILS and
the run must NOT upload that video. A broken video never goes out.
Report: data/qa_report.json per run (pass/fail per check, fixes applied).

Accuracy checklist (history-mystery scripts only; appended to the
same report, same fail-loudly rule): the complete claim ledger must
validate, every script claim ID must exist, and the narration must
match a deterministic rebuild from the reviewed ledger. Sections
carry KNOWN/DEBATED/UNKNOWN tiers and sources remain visible to viewers.
Shock/source checks added for the "Shock, honestly" principle: the
shock hook must be present with tier KNOWN and a filled source, and
every description source entry must either carry a valid URL
(starts with http, contains a dot) or be explicitly flagged as
no-public-URL. A URL is never invented and a malformed URL fails.
This is NOT an automated fact-checker: it cannot verify that a
source is true, only that sources exist, tiers are present, the
shock hook is sourced, URLs look valid, and the mystery is left
open. A human reviewer must still verify the sources themselves
before the peak publish window (see README "Historical accuracy"
and "Shock, honestly"). Accuracy failures are NOT auto-fixed —
there is no safe automatic fix for a missing source — so they
persist through the retry and block upload.
"""

import argparse
import json
import os
import re
import subprocess
import sys

try:
    from src.video import build_video
except ImportError:
    from video import build_video


def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return result


def probe(video):
    result = run_cmd(["ffprobe", "-v", "quiet", "-print_format", "json",
                      "-show_streams", "-show_format", video])
    if result.returncode != 0:
        return None
    return json.loads(result.stdout or "{}")


def volumedetect(video):
    result = run_cmd(["ffmpeg", "-i", video, "-af", "volumedetect",
                      "-vn", "-sn", "-dn", "-f", "null", "/dev/null"])
    mean, maximum = None, None
    for line in result.stderr.splitlines():
        if "mean_volume" in line:
            mean = float(line.rsplit(":", 1)[1].strip().replace(" dB", ""))
        if "max_volume" in line:
            maximum = float(line.rsplit(":", 1)[1].strip().replace(" dB", ""))
    return mean, maximum


def detect(video, filter_name, threshold, min_duration):
    """Return list of (start, duration) segments from a detect filter."""
    result = run_cmd(["ffmpeg", "-i", video, "-vf",
                      f"{filter_name}={threshold}:d={min_duration}",
                      "-an", "-f", "null", "/dev/null"])
    segments, current = [], None
    for line in result.stderr.splitlines():
        if f"{filter_name}" in line or "lavfi" in line:
            start = re.search(r"start:\s*([\d.]+)", line)
            dur = re.search(r"duration:\s*([\d.]+)", line)
            if start and dur:
                segments.append((float(start.group(1)), float(dur.group(1))))
    return segments


def remux_gain(video, gain_db):
    tmp = video + ".qa_tmp.mp4"
    result = run_cmd(["ffmpeg", "-y", "-i", video, "-af",
                      f"volume={gain_db}dB", "-c:v", "copy", tmp])
    if result.returncode != 0:
        return False
    os.replace(tmp, video)
    return True


def check(video, narration=None, tolerance=2.0, scripts=None, script_text="",
          title="", fmt="short"):
    """fmt: 'short' expects 1080x1920, 'long' expects 1920x1080."""
    """Run all checks once. Returns (checks, fixes_needed)."""
    checks = []

    def add(name, passed, detail):
        checks.append({"check": name, "status": "pass" if passed else "fail",
                       "detail": detail})

    if not os.path.exists(video) or os.path.getsize(video) == 0:
        add("file_exists", False, "missing or empty")
        return checks, []
    add("file_exists", True, f"{os.path.getsize(video)} bytes")
    info = probe(video)
    if info is None:
        add("probe", False, "ffprobe could not read the file")
        return checks, []
    video_streams = [s for s in info.get("streams", []) if s["codec_type"] == "video"]
    audio_streams = [s for s in info.get("streams", []) if s["codec_type"] == "audio"]
    if not video_streams:
        add("video_stream", False, "no video stream")
        return checks, []
    stream = video_streams[0]
    want = (1920, 1080) if fmt == "long" else (1080, 1920)
    add("resolution", stream.get("width") == want[0] and stream.get("height") == want[1],
        f"{stream.get('width')}x{stream.get('height')} (want {want[0]}x{want[1]} for {fmt})")
    fps = stream.get("avg_frame_rate", "0/1")
    try:
        num, den = fps.split("/")
        fps_value = float(num) / float(den) if float(den) else 0
    except (ValueError, ZeroDivisionError):
        fps_value = 0
    add("frame_rate", abs(fps_value - 30) <= 0.5, f"{fps_value:.2f} fps (want 30)")
    duration = float(info.get("format", {}).get("duration", 0))
    if narration and os.path.exists(narration):
        narration_info = probe(narration)
        ndur = float(narration_info.get("format", {}).get("duration", 0)) if narration_info else 0
        add("duration_matches_narration", abs(duration - ndur) <= tolerance,
            f"video {duration:.1f}s vs narration {ndur:.1f}s (tolerance {tolerance}s)")
    else:
        add("duration_matches_narration", True,
            f"no narration file given; video duration {duration:.1f}s")
    if not audio_streams:
        add("audio_present", False, "no audio stream")
    else:
        add("audio_present", True, f"{len(audio_streams)} audio stream(s)")
        mean, maximum = volumedetect(video)
        if mean is None:
            add("audio_not_silent", False, "volumedetect gave no reading")
        elif maximum is not None and maximum <= -60:
            add("audio_not_silent", False, f"max_volume {maximum} dB — silent")
        elif mean <= -45:
            add("audio_not_silent", False, f"mean_volume {mean} dB — too quiet")
        else:
            add("audio_not_silent", True, f"mean {mean} dB, max {maximum} dB")
        if maximum is not None:
            add("audio_not_clipping", maximum <= -0.5,
                f"max_volume {maximum} dB (clipping above -0.5 dB)")
    black = detect(video, "blackdetect", "pix_th=0.10", 2.0)
    silent = detect(video, "silencedetect", "noise=-40dB", 2.0)
    add("no_long_black_stretches", not black,
        f"{len(black)} black stretch(es) >2s" + (f": {black}" if black else ""))
    add("no_long_silent_stretches", not silent,
        f"{len(silent)} silent stretch(es) >2s" + (f": {silent}" if silent else ""))
    # Title card: black in the first 3 seconds only.
    early_black = detect(video, "blackdetect", "pix_th=0.10", 1.0)
    early = [s for s in early_black if s[0] < 3.0]
    add("title_card_not_black", not early,
        "first 3s contain black" if early else "first 3s are not black")
    # video.py writes captions to video + ".ass"; also accept video stem + ".ass".
    captions = video + ".ass"
    alt = os.path.splitext(video)[0] + ".ass"
    found = captions if os.path.exists(captions) else alt
    if os.path.exists(found) and os.path.getsize(found) > 0:
        add("captions_present", True, f"{found} ({os.path.getsize(found)} bytes)")
    else:
        add("captions_present", False, f"{captions} missing or empty")
    return checks, []


PLACEHOLDER_MARKERS = ("do NOT publish", "placeholder", "to cite before publishing")


def sources_filled(script):
    """True only if sources exist and are not the generator placeholder.

    Sources may be plain strings (legacy) or dicts ({title, url} /
    {title, no_public_url}) — a dict counts as real when its title
    (or URL) is present and not the placeholder text.
    """
    sources = (script or {}).get("sources") or []
    real = []
    for s in sources:
        if isinstance(s, dict):
            text = " ".join(str(v) for v in (s.get("title"), s.get("url")) if v)
        else:
            text = str(s)
        if text and not any(m.lower() in text.lower()
                            for m in PLACEHOLDER_MARKERS):
            real.append(s)
    return bool(real), sources


def _url_looks_valid(url):
    """Basic shape check only: http(s) + a dot. This does NOT prove
    the URL exists or supports the claim — the human reviewer does."""
    if not url or not isinstance(url, str):
        return False
    return url.startswith("http") and "." in url.split("://", 1)[-1]


def _normalized_description_sources(script):
    """Sources as the description will show them: the SEO entry's
    `description_sources` if present (run.py/seo.py output), else the
    script's own `sources`, normalized the same way seo.py does.
    Returns [{title, url, no_public_url}]."""
    raw = script.get("description_sources")
    if raw is None:
        raw = script.get("sources") or []
    normalized = []
    for entry in raw:
        if isinstance(entry, dict):
            url = (entry.get("url") or "").strip() or None
            normalized.append({
                "title": (entry.get("title") or "").strip() or url or "?",
                "url": url,
                "no_public_url": bool(entry.get("no_public_url")) or url is None,
            })
        else:
            text = str(entry).strip()
            if not text or any(m.lower() in text.lower()
                               for m in PLACEHOLDER_MARKERS):
                continue
            if text.startswith("http"):
                normalized.append({"title": text, "url": text,
                                   "no_public_url": False})
            else:
                # Plain title: seo.py renders it flagged as no public
                # URL, so the description entry is explicitly flagged.
                normalized.append({"title": text, "url": None,
                                   "no_public_url": True})
    return normalized


def check_accuracy(script):
    """Accuracy checklist for a history-mystery script dict.

    Returns a list of {check, status, detail} entries. Non-history
    scripts (or no script) get a single not-applicable pass, so the
    gate only blocks history-mystery output — the format the
    accuracy principle governs.
    """
    checks = []

    def add(name, passed, detail):
        checks.append({"check": name, "status": "pass" if passed else "fail",
                       "detail": detail})

    if not script or script.get("style") != "history_mystery":
        add("accuracy_applies", True,
            "not a history_mystery script; accuracy checklist not applicable")
        return checks
    # Claim-level evidence gate: every referenced claim must exist in the
    # validated ledger and every claim/source must have human review.
    try:
        from src.evidence import load_ledger, validate_ledger
    except ImportError:
        from evidence import load_ledger, validate_ledger
    ledger = load_ledger("data/evidence_ledger.json")
    ledger_errors = validate_ledger(ledger)
    script_claim_ids = set(script.get("claim_ids") or [])
    ledger_claim_ids = {c.get("claim_id") for c in ledger.get("claims", [])}
    missing_claims = sorted(script_claim_ids - ledger_claim_ids)
    add("accuracy_evidence_ledger_valid", not ledger_errors,
        "ledger validates" if not ledger_errors else "; ".join(ledger_errors[:8]))
    try:
        from src.verification import verify_ledger
    except ImportError:
        from verification import verify_ledger
    verification = verify_ledger(ledger)
    verification_errors = ["{}: {}".format(c["claim_id"], e)
                           for c in verification.get("claims", []) for e in c.get("errors", [])]
    add("accuracy_historical_metadata_verification", not verification_errors,
        "date/source-diversity metadata checks passed" if not verification_errors
        else "; ".join(verification_errors[:8]))
    add("accuracy_claim_ids_in_ledger", bool(script_claim_ids) and not missing_claims,
        "all script claim IDs exist in the ledger" if script_claim_ids and not missing_claims
        else "missing or absent claim IDs: " + ", ".join(missing_claims or ["none supplied"]))
    # Rebuild the expected narration from the ledger and compare it byte-for-byte.
    # This catches unsupported edits made after script generation.
    try:
        from src.documentary import build_documentary
        expected_script = build_documentary(script.get("topic", ""), script.get("format", "short"), ledger)
        script_matches = (script.get("text") == expected_script.get("text")
                          and script_claim_ids == set(expected_script.get("claim_ids") or []))
        match_detail = "script text and claim references match the reviewed ledger"
    except Exception as exc:
        script_matches = False
        match_detail = "could not rebuild from reviewed evidence: " + str(exc)
    add("accuracy_script_matches_ledger", script_matches, match_detail)
    filled, sources = sources_filled(script)
    add("accuracy_sources_filled", filled,
        f"{len(sources)} source(s) listed"
        if filled else "sources field is empty or still the placeholder — "
                      "fill in real, verified sources before publishing")
    sections = script.get("sections") or []
    tiers = {"KNOWN", "DEBATED", "UNKNOWN"}
    untagged = [s.get("title", "?") for s in sections if s.get("tier") not in tiers]
    add("accuracy_sections_tagged", bool(sections) and not untagged,
        f"{len(sections)} section(s), all tiered KNOWN/DEBATED/UNKNOWN"
        if sections and not untagged
        else f"untagged section(s): {untagged or 'no sections present'}")
    has_known = any(s.get("tier") == "KNOWN" for s in sections)
    add("accuracy_known_has_source", (not has_known) or filled,
        "KNOWN sections are backed by filled sources"
        if (not has_known) or filled
        else "KNOWN section(s) present but sources are not filled")
    combined = " ".join([script.get("cta", ""), script.get("text", "")])
    has_question = ("what do you think happened" in combined.lower()
                    and "?" in combined)
    add("accuracy_ending_open_question", has_question,
        "ending asks an open viewer question ('What do you think happened?')"
        if has_question
        else "ending does not contain an open viewer question — "
             "the mystery must be left open for viewer speculation")
    # (a) Shock hook: present, tier KNOWN, with a filled, non-placeholder
    # source. An unsourced shock claim is dropped by drop_unverified
    # and therefore arrives here as a missing hook — which fails.
    hook = script.get("shock_hook") or {}
    hook_source = hook.get("source") or {}
    hook_ok = (
        bool(hook.get("text"))
        and hook.get("tier") == "KNOWN"
        and bool(hook_source.get("title"))
        and not any(m.lower() in str(hook_source.get("title", "")).lower()
                    for m in PLACEHOLDER_MARKERS)
        and (bool(hook_source.get("url")) or hook_source.get("no_public_url"))
    )
    add("accuracy_shock_hook_sourced", hook_ok,
        "shock hook is KNOWN-tier with a filled source"
        if hook_ok
        else "shock hook missing, untiered, or unsourced — supply a "
             "verified shock_fact + shock_source; a shocking claim "
             "without a source must never ship")
    # (b)+(c) Description sources: every entry has a valid URL or is
    # explicitly flagged no-public-URL; no invented/malformed URLs.
    desc_sources = _normalized_description_sources(script)
    bad = []
    for src in desc_sources:
        if src["url"] is not None and not _url_looks_valid(src["url"]):
            bad.append(src["title"])
        elif src["url"] is None and not src["no_public_url"]:
            bad.append(src["title"])
    add("accuracy_description_sources_valid", not bad,
        f"{len(desc_sources)} description source(s): all have a valid URL "
        f"or are explicitly flagged no-public-URL"
        if not bad
        else f"source(s) with a missing/malformed URL or no no-public-URL "
             f"flag: {bad} — never invent a URL; flag it instead")
    return checks


def fix_and_recheck(video, checks, narration=None, script_text="", title="", fmt="short", script=None):
    """Attempt one fix per failing check category, then re-run checks."""
    fixes = []
    failed = {c["check"] for c in checks if c["status"] == "fail"}
    if "audio_not_silent" in failed or "audio_not_clipping" in failed:
        mean, maximum = volumedetect(video)
        if maximum is not None and maximum > -0.5:
            if remux_gain(video, -3.0):
                fixes.append("audio gain -3 dB (clipping fix)")
        elif mean is not None and mean <= -45 and mean > -60:
            gain = min(12.0, -25.0 - mean)
            if remux_gain(video, gain):
                fixes.append(f"audio gain +{gain:.1f} dB (too-quiet fix)")
    if (failed & {"resolution", "no_long_black_stretches", "captions_present",
                  "title_card_not_black"}) and script_text:
        # Re-render with fallback visuals (gradient) and fresh captions.
        # build_video(script_dict, audio_path, output, ...).
        try:
            width, height = (1920, 1080) if fmt == "long" else (1080, 1920)
            build_video({"text": script_text, "topic": title or "Video"},
                        narration or "", video, visuals=[],
                        width=width, height=height)
            fixes.append("re-rendered with fallback visuals + fresh captions")
        except Exception as exc:
            fixes.append(f"re-render FAILED: {exc}")
    elif failed & {"resolution", "no_long_black_stretches", "captions_present",
                   "title_card_not_black"}:
        fixes.append("re-render skipped: no script text available for rebuild")
    new_checks, _ = check(video, narration=narration, script_text=script_text,
                          title=title, fmt=fmt)
    # Accuracy failures are NOT auto-fixable: re-check them, do not clear them.
    new_checks.extend(check_accuracy(script))
    return new_checks, fixes


def run_qa(video, narration=None, script_text="", title="", report_path="data/qa_report.json", fmt="short", script=None):
    checks, _ = check(video, narration=narration, script_text=script_text, title=title, fmt=fmt)
    checks.extend(check_accuracy(script))
    fixes = []
    failed = [c for c in checks if c["status"] == "fail"]
    if failed:
        checks, fixes = fix_and_recheck(video, checks, narration=narration,
                                        script_text=script_text, title=title, fmt=fmt,
                                        script=script)
        failed = [c for c in checks if c["status"] == "fail"]
    overall = "pass" if not failed else "fail"
    report = {"video": video, "overall": overall, "checks": checks,
              "fixes_applied": fixes}
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"QA {overall} for {video} "
          f"({len(checks) - len(failed)}/{len(checks)} checks passed; "
          f"fixes: {fixes or 'none'}) -> {report_path}")
    return overall == "pass"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--narration")
    parser.add_argument("--script-text")
    parser.add_argument("--title", default="")
    parser.add_argument("--format", default="short", choices=["short", "long"])
    parser.add_argument("--report", default="data/qa_report.json")
    parser.add_argument("--script-json", default="",
                        help="JSON file with the full script dict (for the "
                             "accuracy checklist: sources, tiers, ending).")
    args = parser.parse_args(argv)
    script = None
    if args.script_json and os.path.exists(args.script_json):
        with open(args.script_json, encoding="utf-8") as fh:
            script = json.load(fh)
    ok = run_qa(args.video, narration=args.narration,
                script_text=args.script_text or "", title=args.title,
                report_path=args.report, fmt=args.format, script=script)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
