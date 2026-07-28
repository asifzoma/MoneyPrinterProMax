"""Shared paths and constants for the daily finance/tech news brief pipeline."""

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

# RSS feeds for the daily headline pull. Reuters shut down its public RSS feeds
# in 2020, so we use sources confirmed live: CNBC (Finance + Technology
# sections) for market-moving news, plus TechCrunch for tech-industry stories.
# All three require no API key and have no rate limits to manage.
RSS_FEEDS = [
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",  # CNBC Finance
    "https://www.cnbc.com/id/19854910/device/rss/rss.html",  # CNBC Technology
    "https://techcrunch.com/feed/",  # TechCrunch
]
HEADLINE_COUNT = 4  # how many headlines to fold into a single day's script (3-5 requested)

DISCLAIMER = (
    "\n\nDisclaimer: This video is AI-generated commentary for educational and "
    "informational purposes only. It summarizes publicly reported news headlines "
    "and is not financial advice, a recommendation to buy or sell any security, "
    "or a substitute for professional financial guidance. Do your own research "
    "before making any investment decisions."
)

YOUTUBE_PRIVACY_STATUS = os.environ.get("MP_YOUTUBE_PRIVACY", "unlisted")
YOUTUBE_CATEGORY_ID = os.environ.get("MP_YOUTUBE_CATEGORY_ID", "25")  # News & Politics
