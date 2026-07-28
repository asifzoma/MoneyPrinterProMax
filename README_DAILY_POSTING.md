# Daily Posting Instructions

Automated pipeline that pulls today's top finance/tech headlines, generates a
9:16 "daily brief" Short via MoneyPrinterProMax, and saves it locally with
copy-paste-ready title/description/hashtags. **It does not upload anywhere
automatically** — you review and publish each video yourself.

All pipeline code lives in [`daily_pipeline/`](daily_pipeline/).

---

## One-time setup

1. **Fill in MoneyPrinterProMax's own `.env`** (required for any generation to work):
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` and fill in `PEXELS_API_KEY` and `TIKTOK_SESSION_ID` yourself
   (see the main [README.md](README.md) for where to get them). These are
   credentials, so this repo will never fill them in for you.

2. **Start Ollama and the Docker stack** (see main README for full instructions):
   ```bash
   OLLAMA_HOST=0.0.0.0:11434 ollama serve
   ollama pull llama3.1:8b
   docker compose up -d --build
   ```
   > ⚠️ When this pipeline was built, neither `docker` nor `ollama` were found
   > on this machine's PATH, and no install directory was found for either —
   > double check they're actually installed here (not just on another
   > machine), and that you're opening a terminal that has them on PATH,
   > before relying on the scheduler.

3. **Install the pipeline's own Python dependencies:**
   ```bash
   pip install -r daily_pipeline/requirements.txt
   ```

4. **(Optional, only if you later want automated YouTube upload)** —
   `daily_pipeline/upload_youtube.py` exists and works standalone, but is
   *not* wired into the daily scheduler per your instruction to keep this
   local-only. To use it manually later:
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

This fetches headlines, queues a render, waits for it (up to 45 min by
default), and appends a row to `daily_pipeline/tracker.csv`. Logs go to
`daily_pipeline/logs/run_daily.log`. Individual steps can also be run alone:

```bash
python daily_pipeline/fetch_news.py       # just preview today's headlines/topic
python daily_pipeline/generate_video.py   # fetch + generate + save (same as run_daily.py)
```

The finished video and its `TITLE / DESCRIPTION / HASHTAGS / KEYWORDS` sidecar
land in `output/`. Copy-paste from there (or from the `tracker.csv` row) when
you publish manually.

## The tracker (`daily_pipeline/tracker.csv`)

Columns: `Date, Video Filename, Title, Description, Hashtags, YouTube URL, Status`.
Every generated video gets a `Status=Pending` row. `YouTube URL` and the
`Uploaded`/`Failed` states are only ever set if you run `upload_youtube.py`
yourself — otherwise every row just stays `Pending` as a to-publish queue.

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

## API keys & quotas — what to watch

| Key | Where | Notes |
|---|---|---|
| `PEXELS_API_KEY` | `.env` | Free tier; watch for 429s if you batch-generate many videos in a short window. |
| `TIKTOK_SESSION_ID` | `.env` | **Expires periodically** — if voiceover generation starts failing, log into tiktok.com, re-copy the `sessionid` cookie, and update `.env`. |
| RSS feeds | `daily_pipeline/config.py` | No key, no quota. If a feed URL ever 404s/changes, swap it in `RSS_FEEDS`. |
| YouTube Data API v3 (only if you turn on manual/future upload) | `daily_pipeline/client_secret.json` + `token.json` | **Free daily quota is only 10,000 units; one upload costs ~1,600**, so roughly 6 uploads/day tops. Quota resets midnight Pacific Time. `upload_youtube.py` detects a quota error and leaves the row `Pending` to retry later rather than marking it `Failed`. |

---

## Channel growth basics (once you start publishing)

- **Post at a consistent time** — same slot daily builds a habit for the algorithm and for viewers; morning (before market open) or evening (after close) both work, just don't vary it.
- **Test titles and thumbnails**, not just content — for Shorts this mostly means the first frame and the on-screen hook text/title; small wording changes can swing retention a lot.
- **Use 3–5 Shorts hashtags** in the description (`#shorts` plus 2-4 topical ones) — more than that reads as spammy and doesn't help discovery further.
- **Reply to early comments** in the first hour after posting — early engagement velocity is one of the strongest signals for Shorts distribution.
- **Cross-post to TikTok and Instagram Reels** with the same video — re-export or trim the `.mp4` in `output/` as needed; each platform's native audience is different even for identical content.

## AI-generated financial content — policy notes

- YouTube requires **disclosure of "meaningfully altered" or synthetic realistic content** on videos where it could mislead viewers (their "altered or synthetic content" policy). A fully AI-voiced/AI-scripted news commentary short is a reasonable candidate for this label — check YouTube Studio's disclosure toggle at upload time and enable it if prompted.
- Every generated video's description already carries an automatic disclaimer (added in `daily_pipeline/generate_video.py`) stating it's AI-generated commentary/education, not financial advice. Keep this — don't strip it when you edit descriptions before publishing.
- Avoid specific buy/sell recommendations, price targets, or "you should invest in X" framing — the script-generation prompt already instructs this, but skim each script before publishing since LLM output isn't guaranteed to comply every time.
- If you ever monetize this channel, double-check YouTube Partner Program eligibility rules around "repetitious" or "mass-produced" content — a daily news-brief format with real, varying headlines each day is a reasonable case for originality, but pure templated AI content with no variation is the pattern YouTube has cracked down on.
