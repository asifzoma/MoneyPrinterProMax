"""Pull topic-candidate headlines from real film-news RSS feeds and
@cinemashorts' YouTube channel, for manual review.

NOT part of the daily pipeline (run_daily.py/generate_video.py never
import this) and NEVER auto-writes to almost_movies_topics.py -- it only
prints a raw candidate list. Turning a candidate into a FILMS entry is a
separate, manual step that requires actually verifying the claim against
a real primary source first (the film's own Wikipedia article,
contemporary film journalism, etc.) -- same drop-if-unsure discipline as
everywhere else in this pipeline.

@cinemashorts in particular is a video-trivia channel, not a primary
source -- its titles (and every other source's, for that matter) are
leads only. Never add a pool entry on the strength of a headline alone,
regardless of which feed it came from.

Run manually:
    python topic_discovery.py
"""

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

FEEDS = {
    # SlashFilm rebranded to "/Film" -- same outlet, one feed. Listed once,
    # not twice, since https://feeds.feedburner.com/slashfilm's own <title>
    # is literally "/Film" (verified live).
    "SlashFilm (/Film)": "https://feeds.feedburner.com/slashfilm",
    "Collider": "https://collider.com/feed/",
    "Den of Geek": "https://www.denofgeek.com/feed/",
    # channel_id verified live by resolving the @cinemashorts handle page's
    # embedded externalId -- YouTube's native feed only accepts a UC...
    # channel_id, not an @handle.
    "@cinemashorts (YouTube)": (
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCQgVN28p4k6yYbEq9n3OnTg"
    ),
}

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# A bare "Mozilla/5.0" gets silently connection-reset by Collider's
# bot-detection (verified live); a realistic full browser UA string gets
# through to all four feeds.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@dataclass
class Candidate:
    source: str
    title: str
    link: str


def _parse_rss(root: ET.Element) -> list[tuple[str, str]]:
    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title:
            items.append((title, link))
    return items


def _parse_atom(root: ET.Element) -> list[tuple[str, str]]:
    items = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        link_el = entry.find("atom:link", ATOM_NS)
        link = link_el.get("href", "") if link_el is not None else ""
        if title:
            items.append((title, link))
    return items


def fetch_feed(source: str, url: str) -> list[Candidate]:
    """Fetch and parse one feed. Returns [] (never raises) on any
    network/parse failure -- one bad feed shouldn't block the others."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError) as err:
        print(f"  [!] Could not fetch/parse {source}: {err}", file=sys.stderr)
        return []

    if root.tag.endswith("feed"):
        raw_items = _parse_atom(root)
    else:
        raw_items = _parse_rss(root)

    return [Candidate(source=source, title=title, link=link) for title, link in raw_items]


def discover_candidates() -> list[Candidate]:
    candidates = []
    for source, url in FEEDS.items():
        found = fetch_feed(source, url)
        print(f"  {source}: {len(found)} item(s)")
        candidates.extend(found)
    return candidates


if __name__ == "__main__":
    # Some feed titles (@cinemashorts especially) contain emoji that the
    # default Windows console encoding (cp1252) can't display -- replace
    # rather than crash.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("Pulling topic-candidate headlines (leads only -- verify every one before use):\n")
    all_candidates = discover_candidates()
    print(f"\n{len(all_candidates)} raw candidate(s):\n")
    for c in all_candidates:
        print(f"[{c.source}] {c.title}")
        if c.link:
            print(f"  {c.link}")
    print(
        "\nReminder: none of the above is verified. Check each lead against a "
        "real primary source before adding it to almost_movies_topics.py."
    )
