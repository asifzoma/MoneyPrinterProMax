"""Shared paths and constants for the daily "hidden histories of objects" pipeline."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = REPO_ROOT / "output"
LOGS_DIR = PIPELINE_DIR / "logs"

TRACKER_CSV = PIPELINE_DIR / "tracker.csv"
TRACKER_COLUMNS = [
    "Date",
    "Video Filename",
    "Title",
    "Description",
    "Hashtags",
    "YouTube URL",
    "Status",
]

# MoneyPrinterProMax backend API (Docker: http://localhost:8080, see docker-compose.yml)
MP_API_BASE = os.environ.get("MP_API_BASE", "http://localhost:8080").rstrip("/")

# YouTube OAuth. Place your own downloaded OAuth client (Desktop app type) here;
# the token cache is created after the first interactive authorization.
YOUTUBE_CLIENT_SECRETS_FILE = PIPELINE_DIR / "client_secret.json"
YOUTUBE_TOKEN_FILE = PIPELINE_DIR / "token.json"
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Rotation list of everyday objects for the "hidden histories" topic source.
# fetch_topic.py grounds each day's script in the object's real Wikipedia
# summary (rather than letting the LLM invent "facts" from scratch) --
# accuracy matters more in this niche since a wrong claim gets caught fast.
OBJECTS_FILE = PIPELINE_DIR / "objects.txt"
OBJECTS_STATE_FILE = PIPELINE_DIR / ".objects_state.json"
WIKIPEDIA_USER_AGENT = "MoneyPrinterProMax-DailyPipeline/1.0 (personal project; no contact)"

DISCLAIMER = (
    "\n\nThis video is AI-narrated and grounded in the linked object's "
    "Wikipedia summary, simplified for a short-form audience -- always a good "
    "idea to check the source article if you want the full story."
)

YOUTUBE_PRIVACY_STATUS = os.environ.get("MP_YOUTUBE_PRIVACY", "unlisted")
YOUTUBE_CATEGORY_ID = os.environ.get("MP_YOUTUBE_CATEGORY_ID", "27")  # Education
