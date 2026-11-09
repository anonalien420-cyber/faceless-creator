"""Upload only an unlisted draft after explicit human review.

Deep Scan intentionally disables public and scheduled-public uploads.
Manual unlisted uploads require HUMAN_REVIEW_APPROVED=true and
UPLOAD_ENABLED=true. Final public publication must happen manually in
YouTube Studio after the reviewer checks the evidence ledger and queue.
--dry-run performs no network operation.
"""

import argparse
import json
import os
import sys


def plan(video, title, description, privacy, publish_at=None):
    out = {"video": video, "title": title, "description": description,
           "privacyStatus": privacy, "categoryId": "27"}
    if publish_at:
        out["publishAt"] = publish_at
    return out


def upload(video, title, description, privacy, publish_at=None, tags=None):
    # Defense in depth: callers cannot bypass the CLI publishing policy.
    if privacy != "unlisted" or publish_at:
        raise ValueError("Only unlisted, unscheduled uploads are permitted.")
    if os.environ.get("HUMAN_REVIEW_APPROVED", "") != "true":
        raise PermissionError("Human review approval is required before upload.")
    if os.environ.get("UPLOAD_ENABLED", "") != "true":
        raise PermissionError("UPLOAD_ENABLED must be true before upload.")
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
    snippet = {"title": title, "description": description, "categoryId": "27"}
    if tags:
        snippet["tags"] = tags
    body = {"snippet": snippet, "status": status}
    request = youtube.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(video, chunksize=-1, resumable=True))
    response = request.execute()
    video_id = response.get("id")
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
    upload(args.video, args.title, args.description, privacy, tags=tags)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
