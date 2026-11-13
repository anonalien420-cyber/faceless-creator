"""Orchestrate: trends -> scripts -> narrate -> music -> video -> QA -> upload.

Daily cadence (config: long_videos_per_day: 1, shorts_per_day: 2):
- Trends run ONCE for the chosen niche.
- The #1 topic gets the long-form video (16:9, 1920x1080, 8-12 min,
  ~1200-1800 words, chapters/sections).
- The #2 and #3 topics get the Shorts (1080x1920, 30-60s).
- Each output goes through the same narrator/music pipeline, the same
  QA gate (src/qa.py — a failed QA means NO upload for that video),
  and its own peak-time schedule (Shorts window vs long-form window).
- The scheduled workflow is render/review only. Manual unlisted upload
  requires UPLOAD_ENABLED=true and HUMAN_REVIEW_APPROVED=true.
  Public and scheduled-public publishing are disabled in code.
- Any step failure is logged and exits non-zero — never a silent green
  run that did not post. More than 1 long + 2 Shorts per day by default
  is deliberately NOT done: it risks spam and a quality drop (README).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

try:
    from src.job_state import JobState, run_with_retries
except ImportError:
    from job_state import JobState, run_with_retries

try:
    from src.config import load_config
except ImportError:
    from config import load_config

try:
    from src.qa import run_qa
except ImportError:
    from qa import run_qa


def log_step(log, name, status, detail=""):
    entry = {"step": name, "status": status, "detail": detail,
             "at": datetime.now(timezone.utc).isoformat()}
    log["steps"].append(entry)
    print(f"[{status}] {name}: {detail}")
    return entry


def run_cmd(cmd, step, log):
    state = JobState("data/job_state.json", run_id=log.get("started_at"))
    attempts = int(os.environ.get("DEEP_SCAN_STEP_ATTEMPTS", "3") or 3)
    try:
        result = run_with_retries(cmd, step, state=state, attempts=attempts)
    except RuntimeError as exc:
        log_step(log, step, "FAILED", str(exc)[-4000:])
        raise SystemExit("Step failed: {}".format(step))
    log_step(log, step, "ok", (result.stdout or "").strip().splitlines()[-1]
             if result.stdout.strip() else "")
    return result


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "script"


def choose_niche(config, trends_input):
    """One niche per run: explicit --niche wins, else the top-ranked
    niche that actually has candidates, else the first configured niche.
    Never runs every niche in one day (that would spam uploads)."""
    niches = [n for n in (config.get("niches") or []) if n] or (
        [config["niche"]] if config.get("niche") else [])
    if not niches:
        return ""
    result = subprocess.run(
        [sys.executable, "-m", "src.trends", "--rank-niches",
         "--input", trends_input],
        capture_output=True, text=True)
    if result.returncode == 0 and os.path.exists("data/niche_ranking.json"):
        try:
            with open("data/niche_ranking.json", encoding="utf-8") as fh:
                ranking = json.load(fh)["niches"]
            with_candidates = [r for r in ranking if r.get("n_candidates")]
            if with_candidates:
                return with_candidates[0]["niche"]
        except Exception:
            pass
    return niches[0]


def _chapter_description(script, narration_path, total_duration):
    """YouTube chapters block only (timestamps scaled by each section's
    share of the total word count). run.py prepends this to the SEO
    description for long-form uploads."""
    chapters = script.get("chapters") or []
    sections = script.get("sections") or []
    if not chapters or not sections or not total_duration:
        return ""
    total_words = max(1, len(script["text"].split()))
    lines = ["Chapters:"]
    elapsed = 0.0
    # "Intro" covers hook+intro; sections follow; "Summary" is the CTA.
    intro_words = max(1, total_words - sum(len(s["text"].split()) for s in sections)
                      - len(script.get("cta", "").split()))
    segments = [("Intro", intro_words)] + [
        (s["title"], len(s["text"].split())) for s in sections] + [
        ("Summary", len(script.get("cta", "").split()))]
    for title, words in segments:
        minutes, seconds = divmod(int(elapsed), 60)
        lines.append(f"{minutes}:{seconds:02d} {title}")
        elapsed += total_duration * words / total_words
    return "\n".join(lines)


def load_niche_lock():
    """Return the lock dict from data/niche_lock.json, or None."""
    path = "data/niche_lock.json"
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def save_niche_lock(niche):
    os.makedirs("data", exist_ok=True)
    with open("data/niche_lock.json", "w", encoding="utf-8") as fh:
        json.dump({"niche": niche,
                   "locked_since": datetime.now(timezone.utc).isoformat()},
                  fh, indent=2)


def locked_niche(config):
    """Niche lock (recommendation lock): if a lock exists and is younger
    than niche_lock_days, it wins over the daily ranking — stay in one
    niche for subscriber growth. Returns the locked niche or ''."""
    lock = load_niche_lock()
    if not lock or not lock.get("niche") or not lock.get("locked_since"):
        return ""
    try:
        since = datetime.fromisoformat(lock["locked_since"].replace("Z", "+00:00"))
    except ValueError:
        return ""
    days = config.get("niche_lock_days", 90)
    days = 90 if days is None else int(days)
    age = (datetime.now(timezone.utc) - since).days
    if age < days:
        return lock["niche"]
    return ""  # expired: ranking picks the next niche, and a new lock is set


def _audio_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def build_format(log, fmt, scripts, config, niche, args):
    """Narrate -> music -> video -> QA for one format. Returns a list of
    {script, video, narration, qa_report} for outputs that passed QA.
    A QA failure aborts the whole run (no upload of that video, and no
    upload of anything else either — a broken pipeline must not post)."""
    audio_dir = f"data/audio_{fmt}"
    mixed_dir = f"data/audio_mixed_{fmt}"
    video_dir = f"data/videos_{fmt}"
    run_cmd([sys.executable, "-m", "src.narrate", "--input", scripts,
             "--outdir", audio_dir], f"narrate:{fmt}", log)
    with open(scripts, encoding="utf-8") as fh:
        items = json.load(fh)
    os.makedirs(mixed_dir, exist_ok=True)
    outputs = []
    for script in items:
        name = f"{script['rank']:02d}-{slug(script['topic'])}"
        mixed = os.path.join(mixed_dir, f"{name}.mp3")
        run_cmd([sys.executable, "-m", "src.music", "--narration",
                 os.path.join(audio_dir, f"{name}.mp3"), "--output", mixed,
                 "--top5", "data/top5.json"], f"music:{fmt}:{name}", log)
    if not args.skip_video:
        visual_manifest = ""
        comfy_url = os.environ.get("COMFYUI_BASE_URL", "").strip()
        workflow_path = os.environ.get("COMFYUI_IMAGE_WORKFLOW", "").strip()
        if comfy_url and workflow_path:
            by_topic = {}
            media_type = os.environ.get("COMFYUI_MEDIA_TYPE", "image").strip() or "image"
            for script in items:
                asset_dir = os.path.join("data/generated_visuals", fmt, slug(script["topic"]))
                single_script = os.path.join(asset_dir, "script.json")
                os.makedirs(asset_dir, exist_ok=True)
                with open(single_script, "w", encoding="utf-8") as sfh:
                    json.dump(script, sfh, indent=2)
                run_cmd([sys.executable, "-m", "src.visuals", "--script", single_script,
                         "--workflow", workflow_path, "--outdir", asset_dir,
                         "--media-type", media_type, "--base-url", comfy_url],
                        "visual_generation:{}:{}".format(fmt, slug(script["topic"])), log)
                manifest_path = os.path.join(asset_dir, "visual_manifest.json")
                with open(manifest_path, encoding="utf-8") as fh:
                    # The generator accepts a single script file. Extract the
                    # current topic's matching scene manifest from the full list.
                    generated = json.load(fh)
                run_cmd([sys.executable, "-m", "src.visual_qa", "--script",
                         single_script, "--manifest", manifest_path, "--output",
                         os.path.join(asset_dir, "visual_qa.json")],
                        "visual_qa:{}:{}".format(fmt, slug(script["topic"])), log)
                by_topic[script["topic"]] = generated.get("assets", [])
            visual_manifest = os.path.join("data", "generated_visuals", fmt, "visuals_by_topic.json")
            os.makedirs(os.path.dirname(visual_manifest), exist_ok=True)
            with open(visual_manifest, "w", encoding="utf-8") as fh:
                json.dump({"by_topic": by_topic}, fh, indent=2)
        # Funnel end card: Shorts push to the same-day long video;
        # longs tease the next episode.
        end_card = ("Watch the full video today" if fmt == "short"
                    else "Next episode tomorrow")
        run_cmd([sys.executable, "-m", "src.video", "--input", scripts,
                 "--audio-dir", mixed_dir, "--outdir", video_dir,
                 "--format", fmt, "--end-card-text", end_card]
                + (["--visuals-file", visual_manifest] if visual_manifest else []),
                f"video:{fmt}", log)
    qa_reports = []
    for script in items:
        name = f"{script['rank']:02d}-{slug(script['topic'])}"
        video = os.path.join(video_dir, f"{name}.mp4")
        narration = os.path.join(mixed_dir, f"{name}.mp3")
        if not os.path.exists(video):
            continue
        report_path = f"data/qa_report_{fmt}_{name}.json"
        ok = run_qa(video, narration=narration, script_text=script["text"],
                    title=script["topic"], report_path=report_path, fmt=fmt,
                    script=script)
        qa_reports.append(report_path)
        log_step(log, f"qa:{fmt}:{name}", "ok" if ok else "FAILED",
                 f"report {report_path}")
        if not ok:
            # QA gate: fail loudly, upload NOTHING from this run.
            raise SystemExit(
                f"QA FAILED for {video} ({fmt}) — refusing to upload. "
                f"See {report_path}. Fix the render and re-run; a broken "
                "video must never go out.")
        outputs.append({"script": script, "video": video,
                        "narration": narration, "qa_report": report_path,
                        "format": fmt})
    return outputs, qa_reports


def upload_outputs(log, outputs, niche, args, seo_entries=None, long_title=""):
    seo_by_topic = {e["topic"]: e for e in (seo_entries or [])}
    for item in outputs:
        script, video, fmt = item["script"], item["video"], item["format"]
        name = os.path.basename(video)
        seo = seo_by_topic.get(script["topic"])
        title = seo["recommended_title"] if seo else script["topic"].title()
        description = seo["description"] if seo else script["text"][:500]
        if fmt == "long":
            chapters = _chapter_description(
                script, item["narration"], _audio_duration(item["narration"]))
            if chapters:
                description = chapters + "\n\n" + description
            description += "\n\nNext episode lands tomorrow — same series, next topic."
        elif long_title:
            # Funnel: Shorts push to the same-day long video.
            description += f"\n\nWatch the full deep dive today: {long_title}"
        cmd = [sys.executable, "-m", "src.upload", "--video", video,
               "--title", title, "--description", description,
               "--niche", niche, "--format", fmt]
        if seo and seo.get("tags"):
            cmd += ["--tags", ",".join(seo["tags"])]
        if not args.upload:
            cmd.append("--dry-run")
        run_cmd(cmd, f"upload:{fmt}:{name}", log)
        item["upload_title"] = title
        item["upload_description"] = description


def write_review_queue(outputs, niche, config, args, seo_entries, thumb_map):
    """Human review queue (safety net — uploads are UNLISTED only): one entry
    per output with title, thumbnails (both A/B variants), script
    summary, SEO, QA result, and scheduled peak time. The creator
    should glance at this BEFORE the peak window. QA catches technical
    mistakes only — factual/taste mistakes need these human eyes."""
    try:
        from src.scheduler import next_peak_window
    except ImportError:
        from scheduler import next_peak_window
    seo_by_topic = {e["topic"]: e for e in (seo_entries or [])}
    lines = ["# Human review queue — review BEFORE the peak window", "",
             "Uploads are UNLISTED only. There is no public or scheduled-"
             "public path in this pipeline: src/upload.py refuses any "
             "public/scheduled request, and publishing happens manually "
             "in YouTube Studio after a human reviews this queue. "
             "QA catches technical mistakes only (blank video, silent audio, "
             "wrong resolution, missing captions).", "",
             "HISTORICAL ACCURACY (history-mystery videos): before the peak "
             "window, verify every source listed for each video against the "
             "real record. QA only checks that sources exist, sections are "
             "tiered KNOWN/DEBATED/UNKNOWN, and the ending asks an open "
             "viewer question — it cannot verify that a source is TRUE. "
             "Viewer theories in comments are engagement, not evidence; "
             "never present a commenter's theory as fact in a later video.", ""]
    for item in outputs:
        script, video, fmt = item["script"], item["video"], item["format"]
        seo = seo_by_topic.get(script["topic"], {})
        start, _end = next_peak_window(niche, config, fmt=fmt)
        peak = start.isoformat() if start else "no peak window found"
        thumbs = thumb_map.get(script["topic"], [])
        lines.append(f"## [{fmt}] {item.get('upload_title', script['topic'])}")
        lines.append(f"- Video: {video}")
        lines.append(f"- QA: PASS — report {item.get('qa_report', '')}")
        lines.append(f"- Scheduled peak time ({fmt} window): {peak}"
                     + (" (dry-run: would schedule here)" if not args.upload else ""))
        lines.append(f"- Script summary: {script['text'][:200]}...")
        if script.get("style") == "history_mystery":
            lines.append(f"- Accuracy: tiers "
                         f"{[s.get('tier') for s in script.get('sections', [])]}; "
                         f"sources: {script.get('sources', [])}; "
                         f"dropped_unverified: {script.get('dropped_unverified', [])} "
                         "— VERIFY sources against the real record before publishing.")
            lines.append(f"- Evidence claim IDs: {script.get('claim_ids', [])}")
            lines.append("- Visual disclosure: " + script.get("visual_disclaimer", "AI visuals must be labelled as reconstructions."))
            for scene in script.get("scenes", []):
                lines.append(f"  - Scene {scene.get('scene')}: {scene.get('visual_type')}")
                lines.append(f"    Image prompt: {scene.get('image_prompt')}")
                lines.append(f"    Animation prompt: {scene.get('animation_prompt')}")
        lines.append(f"- SEO titles: {', '.join(seo.get('titles', []))}")
        lines.append(f"- Tags: {', '.join(seo.get('tags', []))}")
        lines.append(f"- Pinned-comment question: {seo.get('pinned_comment', '')}")
        if thumbs:
            lines.append("- Thumbnails (A/B pick one):")
            for thumb in thumbs:
                lines.append(f"  - variant {thumb['variant']}: {thumb['path']} "
                             f"(text: {thumb['text']!r}, QA: "
                             f"{'PASS' if thumb['qa_ok'] else 'FAIL — ' + thumb['qa_detail']})")
        else:
            lines.append("- Thumbnails: none generated (Pillow missing or step skipped) — "
                         "add one manually before publishing.")
        lines.append("")
    with open("data/review_queue.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Review queue -> data/review_queue.md ({len(outputs)} video(s))")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--trends-input", default="data/trends_input.json")
    parser.add_argument("--upload", action="store_true", help="Actually upload (needs UPLOAD_ENABLED=true).")
    # NOTE: there is deliberately NO --public / --auto-public /
    # --publish-at-peak flag here. Public or scheduled publishing is
    # disabled in src/upload.py and happens only manually in YouTube
    # Studio after human review. Do not re-add these flags.
    parser.add_argument("--niche", default="",
                        help="Run one chosen niche only (overrides ranking).")
    parser.add_argument("--list-niches", action="store_true",
                        help="Print the niche ranking and stop (no videos, no upload).")
    parser.add_argument("--skip-video", action="store_true")
    parser.add_argument("--long-count", type=int, default=0,
                        help="Override long_videos_per_day (default from config).")
    parser.add_argument("--short-count", type=int, default=0,
                        help="Override shorts_per_day (default from config).")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.list_niches:
        result = subprocess.run(
            [sys.executable, "-m", "src.trends", "--rank-niches",
             "--input", args.trends_input])
        return result.returncode
    if args.niche:
        niche = args.niche  # explicit --niche overrides the niche lock for one run
    elif locked_niche(config):
        niche = locked_niche(config)
        print(f"Niche lock: staying with '{niche}' (niche_lock_days="
              f"{config.get('niche_lock_days', 90)}; --niche overrides for one run).")
    else:
        niche = choose_niche(config, args.trends_input)
        save_niche_lock(niche)
        print(f"Niche lock set: '{niche}' for {config.get('niche_lock_days', 90)} days.")
    long_count = args.long_count or int(config.get("long_videos_per_day", 1) or 1)
    short_count = args.short_count or int(config.get("shorts_per_day", 2) or 2)
    log = {"started_at": datetime.now(timezone.utc).isoformat(),
           "niche": niche, "long_videos": long_count,
           "shorts": short_count, "steps": []}
    os.makedirs("data", exist_ok=True)
    all_outputs, all_qa = [], []
    try:
        run_cmd([sys.executable, "-m", "src.trends", "--input", args.trends_input,
                 "--niche", niche,
                 "--output", "data/top5.json", "--compare", "data/compare.md"],
                "trends", log)
        with open("data/top5.json", encoding="utf-8") as fh:
            top5 = json.load(fh)["candidates"]
        # Research is discovery only. Results are added to the evidence ledger
        # as UNREVIEWED; no discovered source can become a factual claim
        # without an explicit human review in the ledger.
        if "history" in niche.lower():
            run_cmd([sys.executable, "-m", "src.research", "--query", niche,
                     "--output", "data/research_sources.json"],
                    "historical_research", log)
            run_cmd([sys.executable, "-m", "src.source_archive", "--input",
                     "data/research_sources.json", "--output",
                     "data/research_sources_archived.json"],
                    "historical_source_archive", log)
            # Metadata verification is a separate report, never an automatic
            # source approval or truth score. The evidence ledger remains the gate.
            # Create a human-readable review packet for the lead episode.
            # It contains discovery candidates only; it never approves a
            # source or invents a factual claim.
            research_topic = (top5[0].get("title") or top5[0].get("topic")
                              or niche) if top5 else niche
            run_cmd([sys.executable, "-m", "src.review_packet",
                     "--input", "data/research_sources.json",
                     "--ledger", "data/evidence_ledger.json",
                     "--topic", research_topic,
                     "--output", "data/review_packet.md",
                     "--json-output", "data/review_packet.json"],
                    "historical_review_packet", log)
            if os.path.exists("data/evidence_ledger.json"):
                run_cmd([sys.executable, "-m", "src.verification", "--ledger",
                         "data/evidence_ledger.json", "--output",
                         "data/verification_report.json"],
                        "historical_verification", log)
        # Long-form uses #1 in depth; Shorts use #2 and #3 (or fewer if
        # the top 5 is short). One trends run feeds both formats.
        long_cands = top5[:long_count]
        short_cands = top5[long_count:long_count + short_count]
        with open("data/top5_long.json", "w", encoding="utf-8") as fh:
            json.dump(long_cands, fh, indent=2)
        with open("data/top5_shorts.json", "w", encoding="utf-8") as fh:
            json.dump(short_cands, fh, indent=2)
        run_cmd([sys.executable, "-m", "src.script", "--input", "data/top5_long.json",
                 "--output", "data/scripts_long.json", "--format", "long",
                 "--count", str(long_count)], "scripts:long", log)
        run_cmd([sys.executable, "-m", "src.script", "--input", "data/top5_shorts.json",
                 "--output", "data/scripts_shorts.json", "--format", "short",
                 "--count", str(short_count)], "scripts:short", log)
        for fmt, scripts_file in (("long", "data/scripts_long.json"),
                                  ("short", "data/scripts_shorts.json")):
            outputs, qa_reports = build_format(log, fmt, scripts_file,
                                               config, niche, args)
            all_outputs.extend(outputs)
            all_qa.extend(qa_reports)
        # Combined QA report for the run (per-video reports also exist).
        with open("data/qa_report.json", "w", encoding="utf-8") as fh:
            json.dump({"run": log["started_at"], "niche": niche,
                       "reports": all_qa,
                       "videos": [o["video"] for o in all_outputs]}, fh, indent=2)
        log_step(log, "qa:all", "ok",
                 f"{len(all_outputs)} video(s) passed QA: "
                 + ", ".join(o["video"] for o in all_outputs))
        # Series episode: incremented ONLY here, after successful render
        # + QA pass (never before, never on a failed run).
        episode = None
        series_name = config.get("series_name", "") if config.get("series_enabled") else ""
        if series_name:
            state_path = "data/series_state.json"
            state = {"next_episode": 1, "episodes": []}
            if os.path.exists(state_path):
                with open(state_path, encoding="utf-8") as fh:
                    state = json.load(fh)
            episode = int(state.get("next_episode", 1))
            state["episodes"].append({"episode": episode, "date": log["started_at"],
                                      "niche": niche,
                                      "videos": [o["video"] for o in all_outputs]})
            state["next_episode"] = episode + 1
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
            log_step(log, "series", "ok", f"episode {episode} (series: {series_name})")
        # Thumbnails: 2 clickbait-style, truth-checked variants per video.
        thumb_map = {}
        try:
            from src.thumbnail import generate_variants
        except ImportError:
            try:
                from thumbnail import generate_variants
            except ImportError:
                generate_variants = None
        if generate_variants is not None:
            for item in all_outputs:
                script, fmt = item["script"], item["format"]
                n_items = (len(script.get("sections", [])) if fmt == "long" else 3)
                try:
                    results = generate_variants(
                        script["topic"], script["text"], "data/thumbnails",
                        slug(script["topic"]), video=item["video"], fmt=fmt,
                        n_items=n_items)
                    thumb_map[script["topic"]] = results
                    if not all(r["qa_ok"] for r in results):
                        log_step(log, f"thumbnail:{fmt}:{slug(script['topic'])}",
                                 "WARNING", "a thumbnail variant failed QA — "
                                 "flagged in the review queue, video QA unaffected")
                except Exception as exc:
                    log_step(log, f"thumbnail:{fmt}:{slug(script['topic'])}",
                             "WARNING", f"thumbnail generation failed ({exc})")
            with open("data/thumbnails.json", "w", encoding="utf-8") as fh:
                json.dump(thumb_map, fh, indent=2)
        else:
            log_step(log, "thumbnails", "WARNING",
                     "Pillow/thumbnail module unavailable — no thumbnails generated")
        # SEO (titles, description, tags, pinned comment, thumbnails).
        run_cmd([sys.executable, "-m", "src.seo", "--long", "data/scripts_long.json",
                 "--short", "data/scripts_shorts.json", "--output", "data/seo.json",
                 "--thumbnails-file", "data/thumbnails.json",
                 "--series-name", series_name,
                 "--episode", str(episode or 0)], "seo", log)
        seo_entries = []
        if os.path.exists("data/seo.json"):
            with open("data/seo.json", encoding="utf-8") as fh:
                seo_entries = json.load(fh)
            try:
                from src.growth import lint_metadata
            except ImportError:
                from growth import lint_metadata
            metadata_reports = [{"topic": e.get("topic"), **lint_metadata(e)} for e in seo_entries]
            with open("data/metadata_qa.json", "w", encoding="utf-8") as fh:
                json.dump(metadata_reports, fh, indent=2)
            metadata_errors = [r for r in metadata_reports if not r["passed"]]
            if metadata_errors:
                raise SystemExit("Metadata QA blocked publishing: {}".format(metadata_errors))
            log_step(log, "metadata_qa", "ok", "{} metadata package(s) passed".format(len(metadata_reports)))
        long_title = ""
        for entry in seo_entries:
            if entry["format"] == "long":
                long_title = entry["recommended_title"]
                break
        # Upload step: dry-run unless explicitly enabled.
        upload_outputs(log, all_outputs, niche, args,
                       seo_entries=seo_entries, long_title=long_title)
        # Human review queue — always written, even for dry runs.
        write_review_queue(all_outputs, niche, config, args, seo_entries, thumb_map)
    except SystemExit as exc:
        log["status"] = "FAILED"
        with open("data/run_log.json", "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        raise
    log["status"] = "ok"
    log["finished_at"] = datetime.now(timezone.utc).isoformat()
    with open("data/run_log.json", "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)
    print(f"Run complete: {long_count} long-form + {short_count} Shorts. "
          "Log: data/run_log.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
