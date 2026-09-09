"""Delete local .mp4/.srt files for successfully uploaded videos once they've
aged out of the most recent KEEP_COUNT uploads -- keeps output/ from growing
unbounded while the full history stays in tracker.csv (and on YouTube). The
tracker row itself is never touched, only the local files. The .txt metadata
sidecar is deliberately left alone too (out of scope -- see run_daily.py).

Runs at the end of run_daily.py after a successful upload, not as a separate
scheduled job.
"""

from pathlib import Path
from typing import Optional

import tracker
from config import OUTPUT_DIR

KEEP_COUNT = 7


def cleanup_old_output(
    keep_count: int = KEEP_COUNT,
    rows: Optional[list[dict]] = None,
    output_dir: Optional[Path] = None,
) -> list[str]:
    """Delete .mp4/.srt files for uploaded videos beyond the `keep_count`
    most recent successful uploads (ordered by the tracker's Date column,
    most recent first).

    `rows` and `output_dir` default to the real tracker.csv and output/ --
    overridable so this can be tested against synthetic data without
    touching either (see the test in the same PR/commit as this file).

    Returns the list of video filenames whose files were removed.
    """
    if rows is None:
        rows = tracker.read_rows()
    if output_dir is None:
        output_dir = OUTPUT_DIR

    uploaded = [r for r in rows if r.get("Status") == "Uploaded"]
    uploaded.sort(key=lambda r: r.get("Date", ""), reverse=True)

    to_clean = uploaded[keep_count:]
    removed = []
    for row in to_clean:
        filename = row.get("Video Filename")
        if not filename:
            continue
        mp4_path = output_dir / filename
        srt_path = mp4_path.with_suffix(".srt")
        deleted_any = False
        for path in (mp4_path, srt_path):
            if path.exists():
                path.unlink()
                deleted_any = True
        if deleted_any:
            removed.append(filename)
    return removed
