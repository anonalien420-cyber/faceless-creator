"""Upload only an unlisted draft after explicit human review.

Deep Scan intentionally disables public and scheduled-public uploads.
Manual unlisted uploads require HUMAN_REVIEW_APPROVED=true and
UPLOAD_ENABLED=true. Final public publication must happen manually in
YouTube Studio after the reviewer checks the evidence ledger and queue.
--dry-run performs no network operation.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

# Upload state: fingerprints of completed uploads, so a retry never
# creates a duplicate video. Written atomically, owner-only (0600).
DEFAULT_UPLOAD_STATE_PATH = "data/upload_state.json"
UPLOAD_STATE_SCHEMA_VERSION = 1
# Resumable-upload retries: a transient 5xx / 429 / network error
# resumes the same upload; a non-retryable 4xx fails fast.
_MAX_UPLOAD_ATTEMPTS = 3
_RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def upload_fingerprint(video, title, description):
    """Stable fingerprint of one upload: file bytes + title + description.

    The same video file uploaded with a different title/description is
    a different upload (a new video), while an exact retry of the same
    upload has the same fingerprint and must not create a duplicate.
    """
    digest = hashlib.sha256()
    with open(video, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    digest.update(b"\0")
    digest.update(title.encode("utf-8"))
    digest.update(b"\0")
    digest.update((description or "").encode("utf-8"))
    return digest.hexdigest()


def load_upload_state(path=DEFAULT_UPLOAD_STATE_PATH):
    """Load the upload-state file; a missing or corrupt file is an
    empty state (uploads proceed normally — state is a dedup aid,
    never a gate that can block a legitimate upload)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if (data.get("schema_version") == UPLOAD_STATE_SCHEMA_VERSION
                and isinstance(data.get("uploads"), dict)):
            return data
    except (OSError, ValueError):
        pass
    return {"schema_version": UPLOAD_STATE_SCHEMA_VERSION, "uploads": {}}


def _save_upload_state(state, path=DEFAULT_UPLOAD_STATE_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def find_completed_upload(state, fingerprint):
    """Video id already uploaded for this fingerprint, or None."""
    entry = state.get("uploads", {}).get(fingerprint)
    if isinstance(entry, dict) and entry.get("video_id"):
        return entry["video_id"]
    return None


def record_completed_upload(state, fingerprint, video_id, video, title,
                            path=DEFAULT_UPLOAD_STATE_PATH):
    state.setdefault("uploads", {})[fingerprint] = {
        "video_id": video_id, "video": video, "title": title,
        "recorded_at": datetime.now(timezone.utc).isoformat()}
    _save_upload_state(state, path)


def _is_retryable_upload_error(exc):
    """True for transient failures worth resuming: network errors
    (no HTTP status attached) and HTTP 408/429/5xx. A 4xx from the
    API (bad title, bad metadata) will fail the same way on retry,
    so it fails fast instead of burning attempts."""
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None) if resp is not None else None
    if status is None:
        return True
    try:
        return int(status) in _RETRYABLE_HTTP_STATUSES
    except (TypeError, ValueError):
        return True


def resumable_upload(request, max_attempts=_MAX_UPLOAD_ATTEMPTS,
                     sleep=time.sleep):
    """Drive a googleapiclient resumable insert request to completion.

    Uses next_chunk() (not execute()) so a transient failure resumes
    the same server-side upload instead of restarting from scratch:
    the request object keeps its upload state and the next call
    continues where the server left off. Returns the response dict
    (with the video "id") once the upload completes.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            _status, response = request.next_chunk()
            if response is not None:
                return response
            last_exc = RuntimeError(
                "resumable upload returned no progress and no response")
        except Exception as exc:  # transient or API error; see below
            last_exc = exc
            if not _is_retryable_upload_error(exc):
                raise RuntimeError(
                    "resumable upload failed (not retryable): "
                    f"{exc}") from exc
        if attempt < max_attempts:
            print(f"Upload attempt {attempt} failed ({last_exc}); "
                  f"resuming upload (attempt {attempt + 1}/"
                  f"{max_attempts})...", file=sys.stderr)
            sleep(min(30, 2 ** attempt))
    raise RuntimeError(
        f"resumable upload failed after {max_attempts} attempt(s): "
        f"{last_exc}")


def plan(video, title, description, privacy, publish_at=None):
    # Defense in depth: plan() must enforce the same policy as
    # upload() — unlisted only, never scheduled — so no caller can
    # build a public/scheduled plan through this helper.
    if privacy != "unlisted":
        raise ValueError(
            "Only unlisted uploads are permitted: privacy={!r} was "
            "supplied but this pipeline never uploads public videos. "
            "Upload unlisted and publish manually in YouTube Studio."
            .format(privacy))
    # Scheduled publishing is disabled: reject publish_at loudly
    # instead of silently ignoring it (or scheduling it).
    if publish_at:
        raise ValueError(
            "Scheduled publishing is disabled: publish_at={!r} was "
            "supplied but this pipeline never schedules a publish. "
            "Upload unlisted and publish manually in YouTube Studio."
            .format(publish_at))
    return {"video": video, "title": title, "description": description,
            "privacyStatus": privacy, "categoryId": "27"}


def _save_token(creds, path="token.json"):
    """Write refreshed OAuth credentials with owner-only permissions.

    A freshly written token.json must be mode 600: the plain open()
    write used to leave it at umask-default permissions.
    """
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    os.chmod(path, 0o600)


def upload(video, title, description, privacy, publish_at=None, tags=None,
           state_path=None, max_upload_attempts=_MAX_UPLOAD_ATTEMPTS):
    # Defense in depth: callers cannot bypass the CLI publishing policy.
    if privacy != "unlisted" or publish_at:
        raise ValueError("Only unlisted, unscheduled uploads are permitted.")
    if os.environ.get("HUMAN_REVIEW_APPROVED", "") != "true":
        raise PermissionError("Human review approval is required before upload.")
    if os.environ.get("UPLOAD_ENABLED", "") != "true":
        raise PermissionError("UPLOAD_ENABLED must be true before upload.")
    # Idempotency: a retry of an upload that already completed returns
    # the existing video id WITHOUT calling the API again, so a
    # retried run can never create a duplicate video.
    state_path = state_path or DEFAULT_UPLOAD_STATE_PATH
    fingerprint = upload_fingerprint(video, title, description)
    state = load_upload_state(state_path)
    existing = find_completed_upload(state, fingerprint)
    if existing:
        print(f"Upload already completed for this video "
              f"(fingerprint {fingerprint[:12]}...): video id {existing} "
              f"— skipping re-upload.")
        return existing
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        print(f"ERROR: Google API libraries missing ({exc}). "
              "pip install google-api-python-client google-auth-oauthlib", file=sys.stderr)
        raise SystemExit(1)
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", scopes)
            creds = flow.run_local_server(port=0)
        _save_token(creds)
    youtube = build("youtube", "v3", credentials=creds)
    status = {"privacyStatus": privacy}
    snippet = {"title": title, "description": description, "categoryId": "27"}
    if tags:
        snippet["tags"] = tags
    body = {"snippet": snippet, "status": status}
    request = youtube.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(video, chunksize=-1, resumable=True))
    # Resumable + retried: a transient failure resumes this same
    # upload instead of restarting it, and the completed upload is
    # recorded so a later retry returns the same video id.
    response = resumable_upload(request, max_attempts=max_upload_attempts)
    video_id = response.get("id")
    record_completed_upload(state, fingerprint, video_id, video, title,
                            state_path)
    print(f"Uploaded video id: {video_id}")
    print(f"https://www.youtube.com/watch?v={video_id}")
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
                        help="Rejected: public publishing is disabled; publish manually in YouTube Studio. "
                             "WARNING: full auto-public risks factual/taste "
                             "mistakes QA cannot catch — QA catches technical "
                             "mistakes only. Review data/review_queue.md first.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--publish-at-peak", action="store_true",
                        help="Rejected: scheduled public publishing is disabled.")
    parser.add_argument("--publish-at", default="",
                        help="Rejected: scheduled public publishing is disabled.")
    parser.add_argument("--niche", default="")
    parser.add_argument("--upload-state", default="",
                        help="Path to the upload-state file used for "
                             "retry idempotency (default: "
                             "data/upload_state.json).")
    parser.add_argument("--format", default="", choices=["", "short", "long"],
                        help="Use this format's peak window for --publish-at-peak.")
    args = parser.parse_args(argv)
    # Deep Scan safety policy: no direct-public or scheduled-public publishing.
    if args.public or args.auto_public or args.publish_at_peak or args.publish_at:
        print("ERROR: Public or scheduled publishing is disabled. Review and publish manually in YouTube Studio.", file=sys.stderr)
        return 1
    if args.dry_run:
        print("DRY RUN — nothing uploaded:")
        print(json.dumps(plan(args.video, args.title, args.description, "unlisted"), indent=2))
        return 0
    if os.environ.get("HUMAN_REVIEW_APPROVED", "") != "true":
        print("ERROR: Refusing upload: HUMAN_REVIEW_APPROVED must be set to true after reviewing the evidence ledger and review queue.", file=sys.stderr)
        return 1
    privacy = "unlisted"
    if os.environ.get("UPLOAD_ENABLED", "") != "true":
        print("ERROR: Refusing to upload: UPLOAD_ENABLED is not 'true'. "
              "Use --dry-run, or set UPLOAD_ENABLED=true explicitly.", file=sys.stderr)
        return 1
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] or None
    upload(args.video, args.title, args.description, privacy, tags=tags,
           state_path=args.upload_state or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
