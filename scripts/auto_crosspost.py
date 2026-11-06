"""Draft crossposter for The Deep Scan (2026-11-06).

Posts a video teaser for one already-published video to:
  * a Facebook Page (Graph API), and
  * Reddit (link post via OAuth password flow, stdlib only — no PRAW).

DRAFT — not tested against live APIs. No Facebook Page or Reddit
credentials exist yet (both outstanding, Nov 6), so today this script
fails loudly instead of posting anything. That is deliberate.

Usage (called by .github/workflows/crosspost.yml, manual trigger only):
    python scripts/auto_crosspost.py --video-id RB38KIarTcg [--note "..."]

Queue file: data/crosspost_queue.json — a JSON list of entries:
    {"video_id": "RB38KIarTcg", "title": "...", "hook": "...",
     "platforms": ["facebook", "reddit"], "subreddit": "r/UnsolvedMysteries"}

A video is only crossposted if a human put it in the queue. Nothing here
discovers, picks, or auto-posts videos on its own.

Required environment (GitHub repo secrets):
    FB_PAGE_TOKEN, FB_PAGE_ID
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD
Optional:
    CROSSPOST_NOTE — extra line appended to the teaser.

Exit codes: 0 = posted everywhere requested; 1 = config/queue problem
(missing secrets, video not in queue); 2 = a platform call failed.
On any failure the script reports which platform failed and stops — it
never posts to one platform and silently skips the other.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

QUEUE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "crosspost_queue.json")


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def load_queue(video_id):
    try:
        with open(QUEUE_PATH, encoding="utf-8") as fh:
            queue = json.load(fh)
    except FileNotFoundError:
        fail(f"queue file not found: {QUEUE_PATH} — nothing is queued to post.")
    except json.JSONDecodeError as exc:
        fail(f"queue file is not valid JSON: {exc}")
    for entry in queue:
        if entry.get("video_id") == video_id:
            return entry
    fail(f"video {video_id} is not in the crosspost queue — a human must add it first.")


def teaser_text(entry, note=""):
    url = f"https://www.youtube.com/watch?v={entry['video_id']}"
    lines = [entry.get("hook") or entry.get("title", ""), "", url]
    if note:
        lines.append("")
        lines.append(note)
    return "\n".join(lines).strip()


def post_facebook(entry, text):
    page_id = os.environ.get("FB_PAGE_ID")
    token = os.environ.get("FB_PAGE_TOKEN")
    if not page_id or not token:
        fail("Facebook: FB_PAGE_ID / FB_PAGE_TOKEN secrets are not set.")
    payload = urllib.parse.urlencode({
        "message": text,
        "link": f"https://www.youtube.com/watch?v={entry['video_id']}",
        "access_token": token,
    }).encode()
    req = urllib.request.Request(
        f"https://graph.facebook.com/v21.0/{page_id}/feed",
        data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
    except Exception as exc:  # noqa: BLE001 — report and stop, don't half-post
        print(f"ERROR: Facebook post failed: {exc}", file=sys.stderr)
        sys.exit(2)
    print(f"Facebook: posted (id {body.get('id')})")


def post_reddit(entry, text):
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    username = os.environ.get("REDDIT_USERNAME")
    password = os.environ.get("REDDIT_PASSWORD")
    if not all([client_id, client_secret, username, password]):
        fail("Reddit: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / "
             "REDDIT_USERNAME / REDDIT_PASSWORD secrets are not set.")
    subreddit = entry.get("subreddit", "r/UnsolvedMysteries")
    auth = urllib.request.HTTPBasicAuthHandler()
    # Token exchange (password grant) then link submission, stdlib only.
    import base64
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    token_req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=urllib.parse.urlencode({
            "grant_type": "password", "username": username,
            "password": password,
        }).encode(),
        headers={"Authorization": f"Basic {basic}",
                 "User-Agent": "the-deep-scan-crossposter/0.1"},
        method="POST")
    try:
        with urllib.request.urlopen(token_req, timeout=30) as resp:
            token = json.load(resp)["access_token"]
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Reddit auth failed: {exc}", file=sys.stderr)
        sys.exit(2)
    submit_req = urllib.request.Request(
        "https://oauth.reddit.com/api/submit",
        data=urllib.parse.urlencode({
            "sr": subreddit, "kind": "link",
            "title": entry.get("title", ""),
            "url": f"https://www.youtube.com/watch?v={entry['video_id']}",
            "text": text,
        }).encode(),
        headers={"Authorization": f"bearer {token}",
                 "User-Agent": "the-deep-scan-crossposter/0.1"},
        method="POST")
    try:
        with urllib.request.urlopen(submit_req, timeout=30) as resp:
            body = json.load(resp)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Reddit submit failed: {exc}", file=sys.stderr)
        sys.exit(2)
    if body.get("json", {}).get("errors"):
        print(f"ERROR: Reddit rejected the post: {body['json']['errors']}",
              file=sys.stderr)
        sys.exit(2)
    print(f"Reddit: posted to {subreddit}")


def main(argv):
    if "--video-id" not in argv:
        fail("usage: auto_crosspost.py --video-id <youtube-id> [--note ...]")
    video_id = argv[argv.index("--video-id") + 1]
    note = ""
    if "--note" in argv:
        note = argv[argv.index("--note") + 1]
    note = note or os.environ.get("CROSSPOST_NOTE", "")

    entry = load_queue(video_id)
    platforms = entry.get("platforms", ["facebook", "reddit"])
    text = teaser_text(entry, note)
    print(f"Crossposting {video_id} to: {', '.join(platforms)}")
    if "facebook" in platforms:
        post_facebook(entry, text)
    if "reddit" in platforms:
        post_reddit(entry, text)
    print("Done.")


if __name__ == "__main__":
    main(sys.argv)
