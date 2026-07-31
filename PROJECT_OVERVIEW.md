# Project Overview: Daily "Hidden Histories of Objects" Video Pipeline

## What this is

An automated pipeline that, once a day, picks an everyday object (zipper,
toothbrush, trampoline...) from a rotating list, writes a short "hidden
history" narration grounded in that object's real Wikipedia summary,
narrates it with TikTok TTS, illustrates it with real Wikimedia Commons
photos animated with Ken Burns pans, and renders a finished 9:16 YouTube
Shorts-style video via Remotion. It saves locally with a copy-paste-ready
title/description/hashtags — it does not auto-upload anywhere.

Built on top of an existing open-source project, **MoneyPrinterProMax**
(a fork of FujiwaraChoki/MoneyPrinter), which this pipeline reuses pieces of
but no longer depends on wholesale (see "What changed and why" below).

---

## Where the code lives

- **Pushed to GitHub** (reflects the state through the Docker/Commons-images
  milestone, see below): https://github.com/asifzoma/MoneyPrinterProMax/tree/daily-finance-tech-news-pipeline
  — also open as a PR against the upstream project: https://github.com/hatus819/MoneyPrinterProMax/pull/1
- **Local, not yet pushed:** the most recent rebuild (dropping Docker
  entirely, switching final video assembly to Remotion) exists only on this
  machine right now, in the same working directory
  (`C:\Users\User\OneDrive\Money Maker Pro`). Say the word and I'll commit
  and push it so the link above reflects the current design.

All of this project-specific work lives under [`daily_pipeline/`](daily_pipeline/)
and a handful of touched files under [`Backend/`](Backend/) — the rest of
the repo is upstream MoneyPrinterProMax, mostly untouched.

---

## How the pipeline works today

```
daily_pipeline/objects.txt (rotating list, ~40 everyday objects)
  -> fetch_topic.py: pick next object, pull its real Wikipedia summary
  -> Backend/gpt.py (called directly, via local Ollama): write a script
     grounded in that summary, generate title/description/hashtags
  -> Backend/tiktokvoice.py (called directly): TTS narration, one clip
     per sentence, timed to compute caption start/end frames
  -> Backend/commons_search.py (built this session): find real, properly-
     licensed Wikimedia Commons photos -- tries the object's own Wikipedia
     article first (guaranteed on-topic), falls back to a generic Commons
     keyword search
  -> daily_pipeline/remotion/ (Remotion, React-based): renders the final
     video -- Ken Burns pans on the images, animated pop-in captions
     synced to the narration, a title card
  -> output/<slug>-<id>.mp4 + matching .txt (title/description/hashtags/
     photo credits) + a row in daily_pipeline/tracker.csv
```

Everything runs as plain native processes (Python + Node.js). No Docker,
no Postgres, no job queue, no web server.

---

## What changed and why (the short version of a long night)

This started as a finance/tech news brief idea, then went through several
pivots based on real problems hit during development:

1. **Finance/tech news → "hidden histories of objects."** The original
   niche had monetization/compliance friction (financial-advice framing)
   and, once built, felt repetitive. Object-history trivia with real
   Wikipedia grounding is safer and better suited to visual variety.

2. **Docker → native processes.** MoneyPrinterProMax normally runs via
   Docker Compose (Flask API + Postgres + worker + frontend). Docker
   Desktop's own engine crashed repeatedly during development (a
   reproducible stuck-socket bug, unrelated to this project's code) and its
   VM was competing with the local LLM for RAM. Since this pipeline only
   ever runs one job at a time, the Flask/queue/worker layer -- built for a
   multi-user web UI -- wasn't actually needed. Dropping it removed the
   instability entirely.

3. **Pexels stock footage → Wikimedia Commons photos.** Generic stock-video
   search returns mostly irrelevant b-roll for a specific object like
   "safety pin." Commons has real, properly-licensed photos of the actual
   objects (sourced from their own Wikipedia articles first), which is a
   much better content fit -- at the cost of needing careful license
   filtering and photo-credit attribution in the description.

4. **MoviePy assembly → Remotion.** MoviePy's per-frame Python compositing
   produced correct but visually flat results. Remotion (a React-based
   video renderer built for exactly this) gives much richer control over
   animated captions and Ken Burns motion, and further simplified the
   pipeline since it doesn't need the Flask/queue machinery at all --
   it's just: generate content, hand Remotion a JSON file describing it,
   get an mp4 back.

---

## Known limitation (probably environment-specific)

Wikimedia rate-limits `upload.wikimedia.org` (the file-download CDN, not
the search API, which has been 100% reliable) fairly aggressively on the
shared IP this development sandbox uses -- likely from cumulative request
volume across a long testing session, not something your own home network
should hit fresh. The code already retries with backoff and respects
`Retry-After`, but a bad rate-limit window can still make a single run
take several minutes or occasionally fail outright on the image step.

**The most promising fix, not yet built:** since `objects.txt` is a small,
fixed list, cache 2-3 images per object locally the first time each object
is used (or in a one-time seeding pass), so future runs of that object
never touch Wikimedia's file CDN again. This would remove the live-network
dependency from the critical path almost entirely after the first cycle
through the object list.

---

## Repo map (what's actually ours vs. upstream)

| Path | Status |
|---|---|
| `daily_pipeline/` | All new, this project |
| `daily_pipeline/remotion/` | New Remotion project (video rendering) |
| `Backend/commons_search.py` | New (Wikimedia Commons search) |
| `Backend/video.py` | Modified (added `download_image`, Ken Burns helper -- the latter now unused since Remotion replaced MoviePy for final assembly, but left in place) |
| `Backend/pipeline.py` | Modified (Commons image swap, PHOTO CREDITS in metadata sidecar) -- this is upstream's own Flask/worker pipeline, which the daily pipeline itself no longer calls, but still valid for MoneyPrinterProMax's own web UI |
| `Backend/main.py`, `worker.py`, `db.py`, `docker-compose.yml`, `Dockerfile` | Untouched upstream files -- no longer used by the daily pipeline, kept in case you or upstream still want the Docker/web-UI path |
| `README_DAILY_POSTING.md` | Setup/operating instructions for this pipeline specifically |

---

## Running it yourself

See [`README_DAILY_POSTING.md`](README_DAILY_POSTING.md) for full setup.
Short version:

```bash
python daily_pipeline/generate_video.py
```
