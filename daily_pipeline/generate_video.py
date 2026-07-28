"""Generate today's finance/tech news brief video via the MoneyPrinterProMax API.

Pulls headlines, queues a 9:16 job with a 60s minimum duration, waits for the
render, locates the output .mp4 + metadata .txt, and appends a Pending row to
the local CSV tracker.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import tracker
from config import DISCLAIMER, MP_API_BASE, OUTPUT_DIR
from fetch_news import get_daily_topic


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        MP_API_BASE + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str) -> dict:
    with urllib.request.urlopen(MP_API_BASE + path, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_job(job_id: str, poll_seconds: int = 10, max_wait_minutes: int = 45) -> dict:
    """Block until the job reaches a terminal state, or raise after max_wait_minutes."""
    deadline = time.monotonic() + max_wait_minutes * 60
    while True:
        try:
            job = _get(f"/api/jobs/{job_id}")["job"]
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            # A busy backend under heavy CPU load (e.g. Ollama inference
            # competing for cores) can occasionally take longer than the
            # per-request timeout to answer a simple status check; treat
            # that as transient and keep polling rather than aborting.
            print(f"  [!] Poll error: {err}; retrying...")
            time.sleep(poll_seconds)
            continue

        state = job.get("state")
        if state in ("completed", "failed", "cancelled"):
            return job

        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Job {job_id} did not finish within {max_wait_minutes} minutes "
                f"(last state: {state})."
            )
        time.sleep(poll_seconds)


def parse_metadata_txt(text: str) -> dict:
    """Parse the fixed TITLE/DESCRIPTION/HASHTAGS/KEYWORDS sidecar format
    written by Backend/pipeline.py's run_generation_pipeline()."""

    def section(label: str) -> str:
        pattern = rf"^{re.escape(label)}\n(.*?)(?=\n\n[A-Z][A-Z /]*\n|\Z)"
        m = re.search(pattern, text, re.S | re.M)
        return m.group(1).strip() if m else ""

    title = section("TITLE")
    hashtags = section("HASHTAGS")
    keywords = section("KEYWORDS / TAGS")
    description = section("DESCRIPTION")
    # The sidecar repeats the hashtags line once, glued to the end of the
    # description block with no header -- strip that duplicate back off.
    if hashtags and description.endswith(hashtags):
        description = description[: -len(hashtags)].rstrip()

    return {"title": title, "description": description, "hashtags": hashtags, "keywords": keywords}


def generate_daily_video(
    ai_model: str = None,
    voice: str = "en_us_001",
    threads: int = 6,
    min_duration: int = 60,
    aspect_ratio: str = "9:16",
    poll_seconds: int = 10,
    max_wait_minutes: int = 45,
) -> dict:
    ai_model = ai_model or os.environ.get("MP_OLLAMA_MODEL", "llama3.1:8b")

    print("[1/4] Fetching today's headlines...")
    topic, headlines = get_daily_topic()
    for h in headlines:
        print(f"  - [{h['source']}] {h['title']}")

    payload = {
        "videoSubject": topic,
        "aiModel": ai_model,
        "voice": voice,
        "paragraphNumber": 4,
        "aspectRatio": aspect_ratio,
        "minDuration": min_duration,
        "threads": threads,
        "customPrompt": "",
    }

    print(f"\n[2/4] Queuing job to {MP_API_BASE} (aspect {aspect_ratio}, min {min_duration}s)...")
    try:
        resp = _post("/api/generate", payload)
    except urllib.error.URLError as err:
        raise ConnectionError(
            f"Could not reach MoneyPrinterProMax API at {MP_API_BASE}: {err}. "
            f"Is the backend running? (docker compose ps)"
        ) from err

    job_id = resp.get("jobId")
    if not job_id:
        raise RuntimeError(f"API did not return a jobId: {resp}")
    print(f"  queued -> job {job_id}")

    print(f"\n[3/4] Waiting for render (polling every {poll_seconds}s, timeout {max_wait_minutes}m)...")
    job = wait_for_job(job_id, poll_seconds=poll_seconds, max_wait_minutes=max_wait_minutes)

    if job.get("state") != "completed":
        raise RuntimeError(f"Job {job_id} ended in state '{job.get('state')}': {job.get('errorMessage')}")

    result_path = job.get("resultPath")
    if not result_path:
        raise RuntimeError(f"Job {job_id} completed but returned no resultPath.")

    print(f"  done -> {result_path}")

    print("\n[4/4] Locating output files and updating tracker...")
    from config import REPO_ROOT

    video_path = (REPO_ROOT / result_path).resolve()
    txt_path = video_path.with_suffix(".txt")

    if not video_path.exists():
        raise FileNotFoundError(f"Expected video not found: {video_path}")
    if not txt_path.exists():
        raise FileNotFoundError(f"Expected metadata sidecar not found: {txt_path}")

    metadata = parse_metadata_txt(txt_path.read_text(encoding="utf-8"))
    description_with_disclaimer = metadata["description"] + DISCLAIMER

    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    tracker.append_row(
        date=today,
        video_filename=video_path.name,
        title=metadata["title"],
        description=description_with_disclaimer,
        hashtags=metadata["hashtags"],
        youtube_url="",
        status="Pending",
    )
    print(f"  tracker row appended for {video_path.name}")

    return {
        "video_path": str(video_path),
        "txt_path": str(txt_path),
        "title": metadata["title"],
        "description": description_with_disclaimer,
        "hashtags": metadata["hashtags"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate today's finance/tech news brief video.")
    parser.add_argument("--model", default=None, help="Ollama model (default: $MP_OLLAMA_MODEL or llama3.1:8b)")
    parser.add_argument("--voice", default="en_us_001")
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--min-duration", type=int, default=60)
    parser.add_argument("--aspect", default="9:16")
    parser.add_argument("--max-wait-minutes", type=int, default=45)
    args = parser.parse_args()

    try:
        result = generate_daily_video(
            ai_model=args.model,
            voice=args.voice,
            threads=args.threads,
            min_duration=args.min_duration,
            aspect_ratio=args.aspect,
            max_wait_minutes=args.max_wait_minutes,
        )
    except Exception as err:
        print(f"\n[FAILED] {err}", file=sys.stderr)
        sys.exit(1)

    print(f"\nVideo: {result['video_path']}")
    print(f"Title: {result['title']}")
