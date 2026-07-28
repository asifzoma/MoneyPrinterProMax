"""Local CSV tracker: Date, Video Filename, Title, Description, Hashtags, YouTube URL, Status."""

import csv
from typing import Optional

from config import TRACKER_COLUMNS, TRACKER_CSV


def ensure_tracker() -> None:
    """Create tracker.csv with a header row if it doesn't exist yet."""
    if not TRACKER_CSV.exists():
        TRACKER_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(TRACKER_CSV, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(TRACKER_COLUMNS)


def read_rows() -> list[dict]:
    ensure_tracker()
    with open(TRACKER_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def append_row(
    date: str,
    video_filename: str,
    title: str,
    description: str,
    hashtags: str,
    youtube_url: str = "",
    status: str = "Pending",
) -> None:
    ensure_tracker()
    with open(TRACKER_CSV, "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(
            [date, video_filename, title, description, hashtags, youtube_url, status]
        )


def get_next_pending() -> Optional[tuple[int, dict]]:
    """Return (row_index, row_dict) for the first row with Status == Pending, or None."""
    rows = read_rows()
    for i, row in enumerate(rows):
        if row.get("Status") == "Pending":
            return i, row
    return None


def update_row(row_index: int, **fields) -> None:
    """Update specific columns of the row at row_index (0-based, excluding header) and rewrite the CSV."""
    rows = read_rows()
    if row_index < 0 or row_index >= len(rows):
        raise IndexError(f"No tracker row at index {row_index}")

    for key, value in fields.items():
        if key not in TRACKER_COLUMNS:
            raise ValueError(f"Unknown tracker column: {key}")
        rows[row_index][key] = value

    with open(TRACKER_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TRACKER_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
