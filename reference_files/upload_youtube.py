"""Upload the next Pending video from the CSV tracker to YouTube via the
YouTube Data API v3.

First-time setup (must be done once, interactively, by a human):
  1. Create a Google Cloud project, enable the "YouTube Data API v3".
  2. Create an OAuth client ID of type "Desktop app" and download it as JSON.
  3. Save it as daily_pipeline/client_secret.json.
  4. Run:  python upload_youtube.py --authorize-only
     This opens a browser for you to grant consent once; the resulting
     token is cached in daily_pipeline/token.json and silently refreshed
     after that, so the scheduled/unattended runs never need a browser.

Quota note: the YouTube Data API v3 free daily quota is 10,000 units, and a
single video upload costs 1,600 units -- so roughly 6 uploads/day tops on the
default quota. One video/day is comfortably within that.
"""

import argparse
import logging
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

import tracker
from config import (
    LOGS_DIR,
    YOUTUBE_CATEGORY_ID,
    YOUTUBE_CLIENT_SECRETS_FILE,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_SCOPES,
    YOUTUBE_TOKEN_FILE,
)

LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "upload.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("upload_youtube")


class UploadError(Exception):
    """Raised for any failure that should mark the tracker row as Failed
    without crashing the caller (run_daily.py)."""


def get_authenticated_service():
    if not YOUTUBE_CLIENT_SECRETS_FILE.exists():
        raise UploadError(
            f"Missing OAuth client file: {YOUTUBE_CLIENT_SECRETS_FILE}. "
            "Download it from Google Cloud Console (OAuth client, Desktop app "
            "type) and save it at that path."
        )

    creds = None
    if YOUTUBE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(YOUTUBE_TOKEN_FILE), YOUTUBE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as err:
                raise UploadError(
                    f"Could not refresh YouTube OAuth token: {err}. "
                    "Re-run with --authorize-only to re-authenticate."
                ) from err
        else:
            log.info("No cached token found; starting interactive authorization...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(YOUTUBE_CLIENT_SECRETS_FILE), YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        YOUTUBE_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=creds)


def upload_video(
    youtube,
    file_path: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str,
    privacy_status: str,
) -> dict:
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "madeForKids": False,
            "selfDeclaredMadeForKids": False,
        },
    }

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=MediaFileUpload(file_path, chunksize=-1, resumable=True),
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info(f"  upload progress: {int(status.progress() * 100)}%")

    return response


def upload_captions(youtube, video_id: str, srt_path) -> None:
    """Attach an SRT caption track if one exists next to the video.

    Captions are a real (if modest) ranking signal -- YouTube can index
    the spoken content -- and an accessibility win. If your generator
    writes an .srt with the same stem as the video (e.g. from the same
    sentence-timing data used for the on-screen captions), this picks it
    up automatically; if not, this is a no-op.
    """
    if not srt_path.exists():
        return
    try:
        youtube.captions().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "language": "en",
                    "name": "English",
                    "isDraft": False,
                }
            },
            media_body=MediaFileUpload(str(srt_path), mimetype="text/vtt", resumable=False),
        ).execute()
        log.info(f"  captions uploaded from {srt_path.name}")
    except HttpError as err:
        # Non-fatal -- the video itself already uploaded successfully.
        log.warning(f"  caption upload failed (video still uploaded fine): {err}")


def upload_next_pending(privacy_status: str = None, category_id: str = None) -> dict:
    """Upload the first Pending tracker row. Returns a result dict.

    Never raises for expected/operational failures (missing file, quota,
    auth) -- it logs them, marks the row Failed, and returns a dict with
    status="failed" so callers (run_daily.py) can continue instead of
    crashing the whole scheduled run.
    """
    pending = tracker.get_next_pending()
    if pending is None:
        log.info("No Pending rows in tracker.csv. Nothing to upload.")
        return {"status": "skipped", "reason": "no_pending_rows"}

    row_index, row = pending
    from config import OUTPUT_DIR

    video_path = OUTPUT_DIR / row["Video Filename"]

    if not video_path.exists():
        msg = f"Video file not found: {video_path}"
        log.error(msg)
        tracker.update_row(row_index, Status="Failed")
        return {"status": "failed", "reason": msg}

    full_description = row["Description"]
    if row.get("Hashtags"):
        full_description = f"{full_description}\n\n{row['Hashtags']}"
    tags = [h.lstrip("#") for h in row.get("Hashtags", "").split() if h.lstrip("#")]

    try:
        youtube = get_authenticated_service()
        log.info(f"Uploading {video_path.name} as {privacy_status or YOUTUBE_PRIVACY_STATUS}...")
        response = upload_video(
            youtube,
            file_path=str(video_path),
            title=row["Title"],
            description=full_description,
            tags=tags,
            category_id=category_id or YOUTUBE_CATEGORY_ID,
            privacy_status=privacy_status or YOUTUBE_PRIVACY_STATUS,
        )
    except UploadError as err:
        log.error(str(err))
        tracker.update_row(row_index, Status="Failed")
        return {"status": "failed", "reason": str(err)}
    except HttpError as err:
        reason = getattr(err, "reason", str(err))
        log.error(f"YouTube API error ({err.resp.status}): {reason}")
        if err.resp.status == 403 and "quota" in str(reason).lower():
            log.error(
                "This looks like a YouTube Data API daily quota exhaustion "
                "(10,000 units/day; one upload costs ~1,600). It resets at "
                "midnight Pacific Time -- the video stays Pending and will "
                "upload on the next run."
            )
            return {"status": "failed", "reason": "quota_exceeded"}
        tracker.update_row(row_index, Status="Failed")
        return {"status": "failed", "reason": str(reason)}
    except Exception as err:
        log.exception(f"Unexpected error uploading {video_path.name}")
        tracker.update_row(row_index, Status="Failed")
        return {"status": "failed", "reason": str(err)}

    video_id = response.get("id")
    youtube_url = f"https://youtu.be/{video_id}"
    upload_captions(youtube, video_id, video_path.with_suffix(".srt"))
    tracker.update_row(row_index, **{"YouTube URL": youtube_url, "Status": "Uploaded"})
    log.info(f"Uploaded: {youtube_url}")
    return {"status": "uploaded", "youtube_url": youtube_url, "video_id": video_id}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload the next Pending video to YouTube.")
    parser.add_argument(
        "--privacy", choices=["public", "unlisted", "private"], default=None,
        help=f"Overrides the default ({YOUTUBE_PRIVACY_STATUS}).",
    )
    parser.add_argument("--category-id", default=None)
    parser.add_argument(
        "--authorize-only", action="store_true",
        help="Just run the interactive OAuth consent flow and cache the token, then exit.",
    )
    args = parser.parse_args()

    if args.authorize_only:
        get_authenticated_service()
        print(f"Authorization cached at {YOUTUBE_TOKEN_FILE}")
        sys.exit(0)

    result = upload_next_pending(privacy_status=args.privacy, category_id=args.category_id)
    sys.exit(0 if result["status"] in ("uploaded", "skipped") else 1)
