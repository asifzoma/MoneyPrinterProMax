"""Pull today's top finance/tech headlines and format them into a single
MoneyPrinterProMax topic string.

News source: RSS feeds (CNBC Finance, CNBC Technology, TechCrunch). Reuters
retired its public RSS feeds in 2020, so we skip it. RSS needs no API key,
has no daily rate limit, and each of these three feeds returned HTTP 200 with
valid RSS XML when checked directly. NewsAPI.org was the other option but
its free tier caps at 100 requests/day and delays articles by 24h, which
would fight a "today's headlines" daily brief.
"""

import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser

from config import HEADLINE_COUNT, RSS_FEEDS


def _entry_timestamp(entry) -> float:
    for key in ("published", "updated"):
        value = entry.get(key)
        if value:
            try:
                return parsedate_to_datetime(value).timestamp()
            except (TypeError, ValueError):
                pass
    return 0.0


def fetch_headlines(count: int = HEADLINE_COUNT) -> list[dict]:
    """Fetch and return up to `count` headlines, mixed across all feeds.

    Headlines are round-robin interleaved by source (most recent first within
    each feed) rather than globally sorted by recency -- a pure global sort
    lets whichever single outlet happened to post last (e.g. a busy tech blog
    on a quiet finance weekend) crowd out the others, defeating the point of
    pulling from multiple sources.

    Each headline is a dict: {"title": str, "summary": str, "source": str}.
    """
    per_feed = []
    for url in RSS_FEEDS:
        parsed = feedparser.parse(url)
        if parsed.bozo and not parsed.entries:
            print(f"  [!] Could not read feed {url}: {parsed.bozo_exception}", file=sys.stderr)
            per_feed.append([])
            continue
        source = parsed.feed.get("title", url)
        entries = []
        for entry in parsed.entries[:10]:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            summary = (entry.get("summary") or "").strip()
            entries.append(
                {
                    "title": title,
                    "summary": summary,
                    "source": source,
                    "_ts": _entry_timestamp(entry),
                }
            )
        entries.sort(key=lambda item: item["_ts"], reverse=True)
        per_feed.append(entries)

    if not any(per_feed):
        raise RuntimeError("No headlines found in any RSS feed. Check network access / feed URLs.")

    # De-dupe near-identical headlines (e.g. syndicated wire stories) by first-8-words key.
    seen = set()
    deduped = []
    max_len = max((len(feed) for feed in per_feed), default=0)
    for i in range(max_len):
        for feed in per_feed:
            if i >= len(feed):
                continue
            item = feed[i]
            key = " ".join(item["title"].lower().split()[:8])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)

    top = deduped[:count]
    for item in top:
        item.pop("_ts", None)
    return top


def build_topic(headlines: list[dict]) -> str:
    """Format headlines into the videoSubject string fed to MoneyPrinterProMax.

    This intentionally leaves MoneyPrinterProMax's default script prompt and
    min-duration auto-lengthening logic in place (see Backend/pipeline.py) --
    we only shape the *subject*, not a full customPrompt, so the built-in
    minDuration=60 guarantee still works.
    """
    today = datetime.now(timezone.utc).astimezone().strftime("%B %d, %Y")
    headline_lines = "; ".join(f"{i}. {h['title']}" for i, h in enumerate(headlines, 1))

    return (
        f"A fast-paced, punchy daily finance and tech news brief for {today}, "
        f"in the style of a TV business news 'tech check' segment mixed with a "
        f"concise daily news podcast: credible, headline-driven, energetic but "
        f"not sensational. Cover these top stories: {headline_lines}. "
        f"Briefly explain why each story matters. Do not give specific stock buy "
        f"or sell recommendations, price targets, or personalized financial "
        f"advice -- frame everything strictly as commentary and education about "
        f"what happened and why it's notable."
    )


def get_daily_topic(count: int = HEADLINE_COUNT) -> tuple[str, list[dict]]:
    headlines = fetch_headlines(count)
    return build_topic(headlines), headlines


if __name__ == "__main__":
    topic, headlines = get_daily_topic()
    print("Headlines pulled:")
    for h in headlines:
        print(f"  - [{h['source']}] {h['title']}")
    print("\nTopic string for MoneyPrinterProMax:\n")
    print(topic)
