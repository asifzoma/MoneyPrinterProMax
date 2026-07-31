# Daily Posting Instructions

Automated pipeline that picks an everyday object from a rotating list, grounds
a "hidden history" script in its real Wikipedia summary, narrates it with
TikTok TTS, illustrates it with Wikimedia Commons images (Ken Burns pans via
Remotion), and saves a finished 9:16 Short locally with copy-paste-ready
title/description/hashtags. **It does not upload anywhere automatically** —
you review and publish each video yourself.

All pipeline code lives in [`daily_pipeline/`](daily_pipeline/). It runs
entirely natively — no Docker, no Postgres, no Flask job queue. That
machinery existed to support MoneyPrinterProMax's multi-user web UI, which
this single-video-a-day pipeline doesn't need; dropping it also removed the
biggest source of instability during development (Docker Desktop's own
engine crashing repeatedly, unrelated to this project's code).

---

## One-time setup

1. **Fill in `.env`** (repo root):
   ```bash
   cp .env.example .env
   ```
   Fill in `TIKTOK_SESSION_ID` yourself (log into tiktok.com → DevTools →
   Application → Cookies → copy the `sessionid` value). This is a credential,
   so this repo will never fill it in for you. `PEXELS_API_KEY` is no longer
   used by the daily pipeline (footage comes from Wikimedia Commons instead)
   but is still required by MoneyPrinterProMax's own web UI if you use that
   separately.

2. **Install Ollama, uv, FFmpeg, ImageMagick, Node.js** (all one-time, no
   admin/reboot needed):
   ```bash
   winget install -e --id Ollama.Ollama
   winget install -e --id astral-sh.uv
   winget install -e --id Gyan.FFmpeg
   winget install -e --id ImageMagick.ImageMagick
   winget install -e --id OpenJS.NodeJS
   ```
   Then start Ollama and pull the model:
   ```bash
   ollama serve
   ollama pull llama3.1:8b
   ```
   > If you just installed any of these in a terminal that was already open,
   > that terminal won't see them on PATH until you open a fresh one —
   > this tripped us up repeatedly during development.

3. **Install Python dependencies** for the Backend modules the pipeline
   reuses directly (script generation, TTS, image search):
   ```bash
   uv sync
   ```
   (run from the repo root — this uses the `pyproject.toml`/`uv.lock` already
   in this repo)

4. **Install the pipeline's own Python dependencies:**
   ```bash
   pip install -r daily_pipeline/requirements.txt
   ```

5. **Set up the Remotion project** (handles final video rendering — Ken Burns
   pans, animated captions):
   ```bash
   cd daily_pipeline/remotion
   npm install
   ```

6. **(Optional, only if you later want automated YouTube upload)** —
   `daily_pipeline/upload_youtube.py` exists and works standalone, but is
   *not* wired into the daily scheduler. To use it manually later:
   - Create a Google Cloud project → enable **YouTube Data API v3**.
   - Create an OAuth client (type **Desktop app**) → download as JSON →
     save at `daily_pipeline/client_secret.json`.
   - Run once, interactively: `python daily_pipeline/upload_youtube.py --authorize-only`
   - After that: `python daily_pipeline/upload_youtube.py` uploads the next
     `Pending` row and marks it `Uploaded` with the resulting URL.

---

## Running manually

```bash
python daily_pipeline/run_daily.py
```

This picks today's object, generates the script/narration/images, renders
via Remotion, and appends a row to `daily_pipeline/tracker.csv`. Logs go to
`daily_pipeline/logs/run_daily.log`. Individual steps can also be run alone:

```bash
python daily_pipeline/fetch_topic.py       # just preview today's object + Wikipedia grounding
python daily_pipeline/generate_video.py    # fetch + generate + render + save (same as run_daily.py)
```

The finished video and its `TITLE / DESCRIPTION / HASHTAGS / KEYWORDS`
sidecar land in `output/`. The description also carries an automatic
disclaimer plus Wikimedia photo credits (artist/license/source link) for
each image used, satisfying Creative Commons attribution requirements —
don't strip these when you edit before publishing.

## The tracker (`daily_pipeline/tracker.csv`)

Columns: `Date, Video Filename, Title, Description, Hashtags, YouTube URL, Status`.
Every generated video gets a `Status=Pending` row. `YouTube URL` and the
`Uploaded`/`Failed` states are only ever set if you run `upload_youtube.py`
yourself — otherwise every row just stays `Pending` as a to-publish queue.

## The object rotation (`daily_pipeline/objects.txt`)

One everyday object per line. `fetch_topic.py` shuffles through the whole
list before repeating any object (state tracked in the gitignored
`.objects_state.json`), and grounds each script in that object's real
Wikipedia summary — add more objects to the file any time.

## The scheduler

```bash
python daily_pipeline/setup_scheduler.py --time 07:00 --apply
```

Registers a Windows Task Scheduler entry (`MoneyPrinterDailyBrief`) that runs
`run_daily.py` every day at 07:00 local time. Without `--apply` it just prints
what it would do. On macOS/Linux it prints a crontab line for you to add
yourself (it never edits your crontab automatically).

**If the scheduler fails to fire:** open Task Scheduler → find
`MoneyPrinterDailyBrief` → check the "Last Run Result" column, or just run
`python daily_pipeline/run_daily.py` manually and read the output/log.

---

## What to watch

| Piece | Notes |
|---|---|
| `TIKTOK_SESSION_ID` (`.env`) | **Expires periodically** — if voiceover generation starts failing, log into tiktok.com, re-copy the `sessionid` cookie, and update `.env`. |
| Wikimedia Commons image downloads | No API key, but rate-limited per IP if you generate many videos in a short window — the pipeline paces requests and retries with backoff, but a burst of manual test runs can still trip it. |
| YouTube Data API v3 (only if you turn on manual/future upload) | **Free daily quota is only 10,000 units; one upload costs ~1,600**, so roughly 6 uploads/day tops. Quota resets midnight Pacific Time. `upload_youtube.py` detects a quota error and leaves the row `Pending` to retry later rather than marking it `Failed`. |

---

## Channel growth basics (once you start publishing)

- **Post at a consistent time** — same slot daily builds a habit for the algorithm and for viewers.
- **Test titles and thumbnails**, not just content — for Shorts this mostly means the first frame and the on-screen hook text/title; small wording changes can swing retention a lot.
- **Use 3–5 Shorts hashtags** in the description (`#shorts` plus 2-4 topical ones) — more than that reads as spammy and doesn't help discovery further.
- **Reply to early comments** in the first hour after posting — early engagement velocity is one of the strongest signals for Shorts distribution.
- **Cross-post to TikTok and Instagram Reels** with the same video — re-export or trim the `.mp4` in `output/` as needed; each platform's native audience is different even for identical content.

## AI-generated content — policy notes

- YouTube requires **disclosure of "meaningfully altered" or synthetic realistic content** on videos where it could mislead viewers (their "altered or synthetic content" policy). A fully AI-voiced/AI-scripted short is a reasonable candidate for this label — check YouTube Studio's disclosure toggle at upload time and enable it if prompted.
- Every generated video's description carries an automatic disclaimer stating it's AI-narrated and grounded in the linked Wikipedia summary. Keep this — don't strip it when you edit descriptions before publishing.
- Wikimedia Commons images require attribution under their licenses (CC-BY, CC-BY-SA) — the automatic "Image credits" block in the description handles this. Don't remove it.
- If you ever monetize this channel, double-check YouTube Partner Program eligibility rules around "repetitious" or "mass-produced" content — a rotating object list with real Wikipedia-grounded facts each day is a reasonable case for originality, but skim each script before publishing since LLM output isn't guaranteed to stay on-topic every time.
