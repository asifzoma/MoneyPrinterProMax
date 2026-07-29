"""Pick today's object from a rotating list and ground its "hidden history"
in a real Wikipedia summary, then format both into a MoneyPrinterProMax
topic string.

Why Wikipedia grounding: this niche lives or dies on accuracy -- a wrong
"did you know" claim gets called out in comments fast. Rather than let the
LLM invent facts about an object from scratch, we fetch the object's actual
Wikipedia summary (no API key, no rate limit) and instruct the model to draw
only from that summary.

Why a rotating list instead of asking the LLM to pick an object: letting the
model choose tends to gravitate to the same handful of "safe" objects
(paperclip, zipper, ...) run after run -- the exact repetitiveness problem
this niche is meant to solve. A shuffled rotation guarantees every object
gets covered before any repeat.
"""

import json
import random
import sys
import urllib.error
import urllib.parse
import urllib.request

from config import OBJECTS_FILE, OBJECTS_STATE_FILE, WIKIPEDIA_USER_AGENT

WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"


def read_objects() -> list[str]:
    if not OBJECTS_FILE.exists():
        raise RuntimeError(f"Objects list not found: {OBJECTS_FILE}")
    objects = []
    for raw in OBJECTS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            objects.append(line)
    if not objects:
        raise RuntimeError(f"No objects found in {OBJECTS_FILE}")
    return objects


def _load_state() -> dict:
    if OBJECTS_STATE_FILE.exists():
        try:
            return json.loads(OBJECTS_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"order": [], "position": 0}


def _save_state(state: dict) -> None:
    OBJECTS_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _next_objects(objects: list[str], count: int) -> list[str]:
    """Return the next `count` objects from the shuffled rotation, reshuffling
    (and never repeating the object that just finished the previous cycle
    first) whenever the current cycle runs out."""
    state = _load_state()
    order = state.get("order") or []
    position = state.get("position", 0)

    picked = []
    while len(picked) < count:
        if position >= len(order):
            order = list(range(len(objects)))
            random.shuffle(order)
            position = 0
        picked.append(objects[order[position]])
        position += 1

    _save_state({"order": order, "position": position})
    return picked


def fetch_wikipedia_summary(title: str) -> dict | None:
    url = WIKIPEDIA_SUMMARY_URL.format(title=urllib.parse.quote(title.replace(" ", "_")))
    req = urllib.request.Request(url, headers={"User-Agent": WIKIPEDIA_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as err:
        print(f"  [!] Could not fetch Wikipedia summary for '{title}': {err}", file=sys.stderr)
        return None

    extract = (data.get("extract") or "").strip()
    if not extract:
        return None
    return {
        "title": data.get("title", title),
        "extract": extract,
        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
    }


def build_topic(object_name: str, summary: str) -> str:
    return (
        f"A punchy, fast-paced 'hidden history' short about the everyday "
        f"object: {object_name}. Reveal a surprising, lesser-known origin "
        f"story or fact about it and explain why it's surprising. Base every "
        f"claim strictly on this summary -- do not invent or add facts "
        f"beyond what it says: \"{summary}\" "
        f"Make it feel like a fun 'did you know' reveal, not a dry lecture."
    )


def get_daily_topic() -> tuple[str, dict]:
    """Returns (topic_string, meta) where meta has 'object', 'wikipedia_title',
    'wikipedia_url'. Tries a few objects in the rotation in case one's
    Wikipedia page can't be fetched."""
    objects = read_objects()
    candidates = _next_objects(objects, count=min(5, len(objects)))

    for object_name in candidates:
        summary = fetch_wikipedia_summary(object_name)
        if summary:
            topic = build_topic(object_name, summary["extract"])
            meta = {
                "object": object_name,
                "wikipedia_title": summary["title"],
                "wikipedia_url": summary["url"],
            }
            return topic, meta

    raise RuntimeError(
        f"Could not fetch a Wikipedia summary for any of today's candidate "
        f"objects: {candidates}. Check network access or objects.txt entries."
    )


if __name__ == "__main__":
    topic, meta = get_daily_topic()
    print(f"Today's object: {meta['object']} ({meta['wikipedia_url']})")
    print("\nTopic string for MoneyPrinterProMax:\n")
    print(topic)
