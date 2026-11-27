"""Orchestrate: trends -> scripts -> narrate -> music -> video -> QA -> upload.

Daily cadence (config: long_videos_per_day: 1, shorts_per_day: 2):
- Trends run ONCE for the chosen niche.
- The #1 topic gets the long-form video (16:9, 1920x1080, 8-12 min,
  ~1200-1800 words, chapters/sections).
- The #2 and #3 topics get the Shorts (1080x1920, 30-60s).
- Each output goes through the same narrator/music pipeline, the same
  QA gate (src/qa.py — a failed QA means NO upload for that video),
  and its own peak-time schedule (Shorts window vs long-form window).
- Default is dry-run for the upload step (nothing is posted). Pass
  --upload AND set UPLOAD_ENABLED=true to actually upload (privacy
  unlisted unless --public, or private + publishAt with --publish-at-peak).
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


def write_log(log):
    """Write run_log.json, merging steps that subprocesses (narrate/music)
    appended to the on-disk log during this run. run.py keeps its own steps
    in memory; without this merge the final dump would erase the voice and
    music-match details those subprocesses logged."""
    try:
        if os.path.exists("data/run_log.json"):
            with open("data/run_log.json", encoding="utf-8") as fh:
                disk = json.load(fh)
            have = {s.get("step") for s in log.get("steps", [])}
            for s in disk.get("steps", []):
                if s.get("step") not in have:
                    log["steps"].append(s)
    except Exception:
        pass
    os.makedirs("data", exist_ok=True)
    with open("data/run_log.json", "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)


def run_cmd(cmd, step, log):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log_step(log, step, "FAILED", (result.stderr or result.stdout)[-500:])
        raise SystemExit(f"Step failed: {step} (exit {result.returncode})")
    log_step(log, step, "ok", (result.stdout or "").strip().splitlines()[-1]
             if result.stdout.strip() else "")
    return result


def run_step(log, step, cmd, args, module=None, argv=None):
    """Run a pipeline stage either in-process (--in-process) or as a
    subprocess (default). In-process mode calls the stage's main(argv)
    directly, saving ~one Python interpreter startup per stage and
    keeping everything in one process; the subprocess default isolates
    stages and is unchanged. Both log identically and fail loudly."""
    if getattr(args, "in_process", False) and module is not None:
        import contextlib
        import importlib
        import io
        mod = importlib.import_module(module)
        buf = io.StringIO()
        rc = 0
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = mod.main(argv)
        except SystemExit as exc:
            rc = exc.code or 0
        out = buf.getvalue()
        if rc not in (0, None):
            log_step(log, step, "FAILED", out[-500:])
            raise SystemExit(f"Step failed: {step} (exit {rc})")
        last = out.strip().splitlines()[-1] if out.strip() else ""
        log_step(log, step, "ok", last)
        return out
    return run_cmd(cmd, step, log)


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
    narrate_argv = ["--input", scripts, "--outdir", audio_dir]
    run_step(log, f"narrate:{fmt}",
             [sys.executable, "-m", "src.narrate"] + narrate_argv,
             args, module="src.narrate", argv=narrate_argv)
    with open(scripts, encoding="utf-8") as fh:
        items = json.load(fh)
    os.makedirs(mixed_dir, exist_ok=True)
    outputs = []
    for script in items:
        name = f"{script['rank']:02d}-{slug(script['topic'])}"
        mixed = os.path.join(mixed_dir, f"{name}.mp3")
        music_argv = ["--narration", os.path.join(audio_dir, f"{name}.mp3"),
                      "--output", mixed, "--top5", "data/top5.json"]
        run_step(log, f"music:{fmt}:{name}",
                 [sys.executable, "-m", "src.music"] + music_argv,
                 args, module="src.music", argv=music_argv)
    if not args.skip_video:
        # Funnel end card: Shorts push to the same-day long video;
        # longs tease the next episode.
        end_card = ("Watch the full video today" if fmt == "short"
                    else "Next episode tomorrow")
        video_argv = ["--input", scripts, "--audio-dir", mixed_dir,
                      "--outdir", video_dir, "--format", fmt,
                      "--end-card-text", end_card]
        import time as _time
        t0 = _time.monotonic()
        run_step(log, f"video:{fmt}",
                 [sys.executable, "-m", "src.video"] + video_argv,
                 args, module="src.video", argv=video_argv)
        log.setdefault("metrics", {}).setdefault("render_seconds", {})[fmt] = round(
            _time.monotonic() - t0, 2)
    qa_reports = []
    for script in items:
        name = f"{script['rank']:02d}-{slug(script['topic'])}"
        video = os.path.join(video_dir, f"{name}.mp4")
        narration = os.path.join(mixed_dir, f"{name}.mp3")
        if not os.path.exists(video):
            if args.skip_video:
                continue
            raise SystemExit(
                f"Render produced no video for {name} ({fmt}) — refusing to "
                "continue with a missing output (a silent drop would post "
                "fewer videos than the run promised).")
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


def upload_outputs(log, outputs, niche, config, args, seo_entries=None, long_title=""):
    try:
        from src.scheduler import next_peak_window
    except ImportError:
        from scheduler import next_peak_window
    seo_by_topic = {e["topic"]: e for e in (seo_entries or [])}
    # Stagger publish times PER FORMAT so two Shorts in one run do not share
    # a single publishAt (midday + evening), without pushing Shorts past the
    # long-form's evening slot.
    last_scheduled = {}
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
        if args.public or args.auto_public:
            cmd.append("--auto-public" if args.auto_public else "--public")
        if args.publish_at_peak:
            start, _end = next_peak_window(niche, config, fmt=fmt, after=last_scheduled.get(fmt))
            if start is not None:
                last_scheduled[fmt] = start
                item["scheduled_peak"] = start.isoformat()
                cmd += ["--publish-at", start.astimezone(timezone.utc).isoformat()]
            else:
                cmd.append("--publish-at-peak")
        if not args.upload:
            cmd.append("--dry-run")
        run_step(log, f"upload:{fmt}:{name}", cmd, args,
                 module="src.upload", argv=cmd[3:])
        item["upload_title"] = title
        item["upload_description"] = description


def write_review_queue(outputs, niche, config, args, seo_entries, thumb_map):
    """Human review queue (safety net, NOT full auto-public): one entry
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
             "Default uploads are UNLISTED (or private + scheduled with "
             "--publish-at-peak). Nothing here is auto-public unless "
             "--auto-public was passed, and that flag is OFF by default: "
             "full auto-public risks factual/taste mistakes QA cannot catch. "
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
        peak = item.get("scheduled_peak")
        if not peak:
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
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--auto-public", action="store_true",
                        help="Publish publicly immediately (OFF by default). "
                             "WARNING: QA catches technical mistakes only; "
                             "review data/review_queue.md before using this.")
    parser.add_argument("--publish-at-peak", action="store_true",
                        help="Upload private with publishAt = next peak window (Shorts and long-form windows differ).")
    parser.add_argument("--niche", default="",
                        help="Run one chosen niche only (overrides ranking).")
    parser.add_argument("--list-niches", action="store_true",
                        help="Print the niche ranking and stop (no videos, no upload).")
    parser.add_argument("--skip-video", action="store_true")
    parser.add_argument("--in-process", action="store_true",
                        help="Run stages in one process (calls each module's main "
                             "directly) instead of spawning a subprocess per stage. "
                             "Faster (no interpreter startups); subprocess is the default.")
    parser.add_argument("--long-count", type=int, default=None,
                        help="Override long_videos_per_day (default from config; 0 disables long-form).")
    parser.add_argument("--short-count", type=int, default=None,
                        help="Override shorts_per_day (default from config; 0 disables Shorts).")
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
    long_count = (args.long_count if args.long_count is not None
                  else int(config.get("long_videos_per_day", 1) or 1))
    short_count = (args.short_count if args.short_count is not None
                   else int(config.get("shorts_per_day", 2) or 2))
    long_count, short_count = max(0, long_count), max(0, short_count)
    log = {"started_at": datetime.now(timezone.utc).isoformat(),
           "niche": niche, "long_videos": long_count,
           "shorts": short_count, "steps": []}
    os.makedirs("data", exist_ok=True)
    # Reset the on-disk log now (plain overwrite, no merge) so subprocess
    # appends (narrate/music) during this run accumulate on THIS run's log,
    # not the previous run's. The final write_log() merges them back in.
    with open("data/run_log.json", "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)
    all_outputs, all_qa = [], []
    try:
        trends_argv = ["--input", args.trends_input, "--niche", niche,
                       "--output", "data/top5.json", "--compare", "data/compare.md"]
        run_step(log, "trends", [sys.executable, "-m", "src.trends"] + trends_argv,
                 args, module="src.trends", argv=trends_argv)
        with open("data/top5.json", encoding="utf-8") as fh:
            top5 = json.load(fh)["candidates"]
        # Long-form uses #1 in depth; Shorts use #2 and #3 (or fewer if
        # the top 5 is short). One trends run feeds both formats.
        long_cands = top5[:long_count]
        short_cands = top5[long_count:long_count + short_count]
        with open("data/top5_long.json", "w", encoding="utf-8") as fh:
            json.dump(long_cands, fh, indent=2)
        with open("data/top5_shorts.json", "w", encoding="utf-8") as fh:
            json.dump(short_cands, fh, indent=2)
        # Style follows the niche ACTUALLY running this run (which --niche
        # may override), not just the first configured niche — otherwise a
        # finance topic under a history lock still gets history-mystery scripts.
        niche_lower = niche.lower()
        style = ("history_mystery"
                 if ("history" in niche_lower and "myster" in niche_lower)
                 else "general")
        long_argv = ["--input", "data/top5_long.json", "--output", "data/scripts_long.json",
                     "--format", "long", "--style", style, "--count", str(long_count)]
        run_step(log, "scripts:long", [sys.executable, "-m", "src.script"] + long_argv,
                 args, module="src.script", argv=long_argv)
        short_argv = ["--input", "data/top5_shorts.json", "--output", "data/scripts_shorts.json",
                      "--format", "short", "--style", style, "--count", str(short_count)]
        run_step(log, "scripts:short", [sys.executable, "-m", "src.script"] + short_argv,
                 args, module="src.script", argv=short_argv)
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
        try:
            from src.models import Brand
        except ImportError:
            from models import Brand
        brand = Brand.from_config(config)
        if generate_variants is not None:
            for item in all_outputs:
                script, fmt = item["script"], item["format"]
                n_items = (len(script.get("sections", [])) if fmt == "long" else 3)
                try:
                    results = generate_variants(
                        script["topic"], script["text"], "data/thumbnails",
                        slug(script["topic"]), video=item["video"], fmt=fmt,
                        n_items=n_items, brand=brand)
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
        seo_argv = ["--long", "data/scripts_long.json",
                    "--short", "data/scripts_shorts.json", "--output", "data/seo.json",
                    "--thumbnails-file", "data/thumbnails.json",
                    "--series-name", series_name, "--episode", str(episode or 0)]
        run_step(log, "seo", [sys.executable, "-m", "src.seo"] + seo_argv,
                 args, module="src.seo", argv=seo_argv)
        seo_entries = []
        if os.path.exists("data/seo.json"):
            with open("data/seo.json", encoding="utf-8") as fh:
                seo_entries = json.load(fh)
        long_title = ""
        for entry in seo_entries:
            if entry["format"] == "long":
                long_title = entry["recommended_title"]
                break
        # Upload step: dry-run unless explicitly enabled.
        upload_outputs(log, all_outputs, niche, config, args,
                       seo_entries=seo_entries, long_title=long_title)
        # Human review queue — always written, even for dry runs.
        write_review_queue(all_outputs, niche, config, args, seo_entries, thumb_map)
    except SystemExit:
        log["status"] = "FAILED"
        write_log(log)
        raise
    except Exception:
        # Unexpected errors (KeyError, FileNotFoundError, ...) must also
        # leave a FAILED log, not a stale "ok" one from a previous run.
        log["status"] = "FAILED"
        write_log(log)
        raise
    log["status"] = "ok"
    log["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_log(log)
    # Per-run manifest: render time, QA pass rate, upload status — one
    # glanceable metrics file per run (data/run_manifest.json).
    _write_manifest(log, all_outputs, niche, args)
    # Topic memory: record covered topics so future runs do not repeat them.
    if config.get("topic_memory", True):
        try:
            from src.script import record_topics
        except ImportError:
            from script import record_topics
        record_topics([o["script"]["topic"] for o in all_outputs])
    print(f"Run complete: {long_count} long-form + {short_count} Shorts. "
          "Log: data/run_log.json")
    return 0


def _write_manifest(log, outputs, niche, args):
    """Write data/run_manifest.json with per-run production metrics."""
    qa_pass = sum(1 for o in outputs if o.get("qa_report"))
    render_seconds = log.get("metrics", {}).get("render_seconds", {})
    uploads = [{"video": o["video"], "format": o["format"],
                "title": o.get("upload_title", ""),
                "scheduled_peak": o.get("scheduled_peak", ""),
                "uploaded": bool(args.upload)} for o in outputs]
    manifest = {
        "started_at": log.get("started_at"),
        "finished_at": log.get("finished_at"),
        "niche": niche,
        "status": log.get("status"),
        "videos": len(outputs),
        "qa_passed": qa_pass,
        "qa_pass_rate": round(qa_pass / len(outputs), 3) if outputs else 0.0,
        "render_seconds": render_seconds,
        "total_render_seconds": round(sum(render_seconds.values()), 2),
        "in_process": bool(getattr(args, "in_process", False)),
        "uploads": uploads,
    }
    os.makedirs("data", exist_ok=True)
    with open("data/run_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
