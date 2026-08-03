"""Daily orchestrator: pick today's object, generate the hidden-history
video, and (by default) upload it straight to YouTube -- no manual step.

Set MP_AUTO_UPLOAD=false to fall back to the old behaviour (generate only,
leave the tracker row as Pending for you to review/upload by hand).

This is the script the daily scheduler (see setup_scheduler.py) runs.
"""

import logging
import os
import sys

from config import LOGS_DIR
from generate_video import generate_daily_video

LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "run_daily.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("run_daily")

AUTO_UPLOAD = os.environ.get("MP_AUTO_UPLOAD", "true").lower() not in ("false", "0", "no")


def main() -> int:
    log.info("=== Daily hidden-histories-of-objects video: starting ===")
    try:
        result = generate_daily_video()
    except Exception as err:
        log.exception(f"Generation failed: {err}")
        log.info("=== Daily run FAILED (generation) ===")
        return 1

    log.info(f"Video saved: {result['video_path']}")
    log.info(f"Title: {result['title']}")

    if not AUTO_UPLOAD:
        log.info("MP_AUTO_UPLOAD=false -- leaving tracker row as Pending for manual upload.")
        log.info("=== Daily run completed successfully ===")
        return 0

    log.info("Uploading to YouTube...")
    import upload_youtube  # imported lazily so generation still works if google-api libs aren't installed

    try:
        upload_result = upload_youtube.upload_next_pending()
    except Exception as err:
        log.exception(f"Upload failed: {err}")
        log.info("Video was generated successfully and is still Pending in tracker.csv --")
        log.info("re-run `python upload_youtube.py` once the problem above is fixed.")
        log.info("=== Daily run completed with upload FAILURE ===")
        return 2

    if upload_result["status"] == "uploaded":
        log.info(f"Uploaded: {upload_result['youtube_url']}")
        log.info("=== Daily run completed successfully (generated + uploaded) ===")
        return 0

    log.warning(f"Upload did not complete: {upload_result}")
    log.info("Video remains Pending in tracker.csv -- re-run `python upload_youtube.py` later.")
    log.info("=== Daily run completed with upload issue ===")
    return 2


if __name__ == "__main__":
    sys.exit(main())
