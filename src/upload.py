"""Upload a video to YouTube. Draft-like by default, never public by accident.

- Default privacyStatus: "unlisted" (draft-like; not listed, not public).
  This is the human-review-queue flow: run.py writes data/review_queue.md
  for every upload so a human can glance at title, thumbnail, script
  summary, SEO, QA result, and scheduled peak time BEFORE the peak
  window. Review the queue before the peak window.
- --public / --auto-public publish immediately and publicly. --auto-public
  is OFF by default for a reason: full auto-public risks factual and
  taste mistakes that QA cannot catch — QA catches TECHNICAL mistakes
  only (blank video, silent audio, wrong resolution, missing captions).
  Use auto-public only if you accept that risk.
- --publish-at-peak uploads as private with a YouTube publishAt time set
  to the next peak window for the niche (src/scheduler.py). YouTube then
  publishes the video at that time. This is the daily peak-time flow:
  render in the morning, publish at peak, one video per day. Peak times
  are general audience windows, NOT a guarantee of popularity.
- --dry-run prints exactly what WOULD be uploaded and calls no API.
- Real uploads are refused unless UPLOAD_ENABLED=true in the environment.
- Requires client_secrets.json (YouTube Data API OAuth client) on first
  run; the token is then stored in token.json (gitignored, never commit).

Never run this in CI without explicitly setting UPLOAD_ENABLED=true.
"""

import argparse
import json
import os
import sys
import time
from datetime import timezone

try:
    from src.config import load_config
    from src.scheduler import next_peak_window
except ImportError:
    from config import load_config
    from scheduler import next_peak_window


def plan(video, title, description, privacy, publish_at=None, category_id="27"):
    # Match what upload() actually does: scheduled publishing forces private,
    # so the dry run must not advertise "unlisted + publishAt".
    if publish_at:
        privacy = "private"
    out = {"video": video, "title": title, "description": description,
           "privacyStatus": privacy, "categoryId": category_id}
    if publish_at:
        out["publishAt"] = publish_at
    return out


def interpret_upload_status(response):
    """Map a videos.list(status) response to (state, detail). Pure function.

    state is one of: processed, processing, failed, rejected, deleted,
    unknown. YouTube sets status.uploadStatus to 'uploaded'/'processed'
    once the video is ready; 'failed'/'rejected'/'deleted' are terminal
    failures that must never be reported as a successful publish.
    """
    items = (response or {}).get("items", [])
    if not items:
        return "unknown", "video not found (yet)"
    status = items[0].get("status", {})
    upload_status = status.get("uploadStatus", "")
    rejection = status.get("rejectionReason", "")
    failure = status.get("failureReason", "")
    if upload_status == "processed":
        return "processed", "processed and ready"
    if upload_status == "rejected":
        return "rejected", rejection or "rejected by YouTube"
    if upload_status == "failed":
        return "failed", failure or "processing failed"
    if upload_status == "deleted":
        return "deleted", "video deleted"
    if upload_status in ("uploaded", "processing"):
        return "processing", upload_status
    return "unknown", upload_status or "no uploadStatus"


def verify_processed(youtube, video_id, timeout=300, interval=10, sleep=time.sleep):
    """Poll YouTube until the uploaded video finishes processing.

    Returns the final (state, detail). Raises RuntimeError on a terminal
    failure (failed/rejected/deleted) so a broken upload is never recorded
    as published. Returns ('processing', ...) if the timeout elapses while
    YouTube is still processing (the caller can re-check later)."""
    deadline = time.monotonic() + timeout
    state, detail = "processing", "starting"
    while time.monotonic() < deadline:
        response = youtube.videos().list(part="status", id=video_id).execute()
        state, detail = interpret_upload_status(response)
        if state in ("processed", "failed", "rejected", "deleted"):
            break
        sleep(interval)
    if state in ("failed", "rejected", "deleted"):
        raise RuntimeError(f"Upload {video_id} did not process: {state} ({detail})")
    return state, detail


def record_upload_feedback(entry, path="data/upload_feedback.json"):
    """Append a verified-upload record so the review loop can match a
    published video_id back to its script/hook/thumbnail. This closes the
    feedback loop: review.py + analytics.py key on video_id."""
    feedback = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                feedback = json.load(fh)
        except (OSError, ValueError):
            feedback = []
    feedback.append(entry)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(feedback, fh, indent=2)
    return entry


def upload(video, title, description, privacy, publish_at=None, tags=None, category_id="27",
           topic="", fmt="", verify=True, process_timeout=300):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        print(f"ERROR: Google API libraries missing ({exc}). "
              "pip install google-api-python-client google-auth-oauthlib", file=sys.stderr)
        raise SystemExit(1) from exc
    # upload + readonly: the same channel owner's token also feeds the weekly
    # review's stats read (src/review.py needs youtube.readonly). With an
    # upload-only token that read silently always fell back to manual stats.
    scopes = ["https://www.googleapis.com/auth/youtube.upload",
              "https://www.googleapis.com/auth/youtube.readonly"]
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if os.environ.get("CI") or not os.path.exists("client_secrets.json"):
                raise SystemExit(
                    "No valid token.json and an interactive OAuth flow is not "
                    "possible here (headless/CI). Provide a token.json with a "
                    "refresh token (e.g. from the YT_TOKEN secret), or run "
                    "src.upload locally once to consent.")
            flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", scopes)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    youtube = build("youtube", "v3", credentials=creds)
    status = {"privacyStatus": privacy}
    if publish_at:
        # Scheduled publishing requires private + publishAt; YouTube
        # flips it public at publishAt. Never combine publishAt with
        # an immediate public status — the API rejects that.
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    snippet = {"title": title, "description": description, "categoryId": category_id}
    if tags:
        snippet["tags"] = tags
    body = {"snippet": snippet, "status": status}
    # Resumable, chunked upload with retry on transient server errors. A
    # single-shot chunksize=-1 request is fragile for ~1 GB long-form files.
    media = MediaFileUpload(video, chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    retries = 0
    while response is None:
        try:
            _progress, response = request.next_chunk()
        except HttpError as exc:
            if exc.resp.status in (500, 502, 503, 504) and retries < 5:
                retries += 1
                time.sleep(2 ** retries)
                continue
            raise
    video_id = response.get("id")
    print(f"Uploaded video id: {video_id}")
    print(f"https://www.youtube.com/watch?v={video_id}")
    # Verify YouTube actually finished processing before recording a
    # publish. A video stuck in 'failed'/'rejected' must never be logged
    # as successfully uploaded (the review loop would learn from a video
    # that does not exist).
    state, detail = ("processed", "verification disabled")
    if verify and video_id:
        state, detail = verify_processed(youtube, video_id, timeout=process_timeout)
        print(f"Upload processing: {state} ({detail})")
    record_upload_feedback({
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
        "title": title, "topic": topic, "format": fmt,
        "privacy": status.get("privacyStatus"), "publish_at": publish_at,
        "upload_status": state, "detail": detail,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return video_id


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="",
                        help="Comma-separated tags for the video snippet.")
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--auto-public", action="store_true",
                        help="Publish publicly immediately (OFF by default). "
                             "WARNING: full auto-public risks factual/taste "
                             "mistakes QA cannot catch — QA catches technical "
                             "mistakes only. Review data/review_queue.md first.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--publish-at-peak", action="store_true",
                        help="Upload private with publishAt = next peak window for --niche.")
    parser.add_argument("--publish-at", default="",
                        help="Explicit ISO publishAt timestamp (overrides --publish-at-peak).")
    parser.add_argument("--niche", default="")
    parser.add_argument("--topic", default="",
                        help="Script topic, recorded with the video_id for the review loop.")
    parser.add_argument("--format", default="", choices=["", "short", "long"],
                        help="Use this format's peak window for --publish-at-peak.")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    category_id = str(config.get("youtube_category_id", "27") or "27")
    privacy = "public" if (args.public or args.auto_public) else "unlisted"
    publish_at = args.publish_at or None
    if args.publish_at_peak and not publish_at:
        niche = args.niche or (config.get("niches") or [config.get("niche", "")])[0]
        start, _end = next_peak_window(niche, config, fmt=args.format or None)
        if start is None:
            print("ERROR: --publish-at-peak requested but no peak window found "
                  "in the next 14 days. Refusing to upload without a schedule.",
                  file=sys.stderr)
            return 1
        publish_at = start.astimezone(timezone.utc).isoformat()
        privacy = "private"  # required for scheduled publishing
        print(f"Scheduled publishing: private now, publishAt {publish_at} "
              f"(next peak window for niche '{niche}')")
    if args.dry_run:
        print("DRY RUN — nothing uploaded:")
        print(json.dumps(plan(args.video, args.title, args.description, privacy,
                              publish_at=publish_at, category_id=category_id), indent=2))
        return 0
    if os.environ.get("UPLOAD_ENABLED", "") != "true":
        print("ERROR: Refusing to upload: UPLOAD_ENABLED is not 'true'. "
              "Use --dry-run, or set UPLOAD_ENABLED=true explicitly.", file=sys.stderr)
        return 1
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] or None
    upload(args.video, args.title, args.description, privacy,
           publish_at=publish_at, tags=tags, category_id=category_id,
           topic=args.topic, fmt=args.format,
           verify=bool(config.get("verify_upload", True)),
           process_timeout=int(config.get("upload_process_timeout", 300) or 300))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
