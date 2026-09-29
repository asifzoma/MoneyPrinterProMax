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


def _maybe_refill_pool() -> None:
    """Non-fatal by design: pool health is independent of today's
    video/upload outcome, and a refill failure should never affect this
    run's exit code or logs' interpretation of whether the day's video
    succeeded."""
    try:
        import auto_refill_pool

        result = auto_refill_pool.maybe_refill_pool()
        status = result.get("status")
        if status == "skipped":
            log.info("Pool refill: not needed (no pool below threshold).")
        elif status == "refilled":
            log.info(
                f"Pool refill: added {len(result['accepted'])} entries "
                f"(triggered by {', '.join(result['triggered_by'])}): "
                f"{', '.join(result['accepted'])}"
            )
            if result["rejected"]:
                log.info(f"Pool refill: {len(result['rejected'])} candidate(s) failed verification and were dropped.")
        else:
            log.warning(f"Pool refill did not complete cleanly: {result}")
    except Exception as err:
        log.warning(f"Pool refill check failed (day's run unaffected): {err}")


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

    exit_code = 0

    if not AUTO_UPLOAD:
        log.info("MP_AUTO_UPLOAD=false -- leaving tracker row as Pending for manual upload.")
        log.info("=== Daily run completed successfully ===")
    else:
        log.info("Uploading to YouTube...")
        import upload_youtube  # imported lazily so generation still works if google-api libs aren't installed

        try:
            upload_result = upload_youtube.upload_next_pending()
        except Exception as err:
            log.exception(f"Upload failed: {err}")
            log.info("Video was generated successfully and is still Pending in tracker.csv --")
            log.info("re-run `python upload_youtube.py` once the problem above is fixed.")
            log.info("=== Daily run completed with upload FAILURE ===")
            exit_code = 2
        else:
            if upload_result["status"] == "uploaded":
                log.info(f"Uploaded: {upload_result['youtube_url']}")

                try:
                    import cleanup_output

                    removed = cleanup_output.cleanup_old_output()
                    if removed:
                        log.info(
                            f"Cleaned up local files for {len(removed)} older upload(s): "
                            f"{', '.join(removed)}"
                        )
                except Exception as err:
                    log.warning(f"Output cleanup failed (upload still succeeded): {err}")

                log.info("=== Daily run completed successfully (generated + uploaded) ===")
            else:
                log.warning(f"Upload did not complete: {upload_result}")
                log.info("Video remains Pending in tracker.csv -- re-run `python upload_youtube.py` later.")
                log.info("=== Daily run completed with upload issue ===")
                exit_code = 2

    _maybe_refill_pool()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
