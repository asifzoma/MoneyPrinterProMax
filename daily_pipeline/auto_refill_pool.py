"""Autonomous pool-refill: when any of almost_movies_topics.py's three
pools (collapsed/conspiracy/disaster) runs low on undrawn rotation slots,
calls the Anthropic API -- with its native web search tool -- to research,
verify, and append ~50 new entries spanning all three types, then
self-commits and pushes.

Runs at the end of run_daily.py, after that day's video, and is designed
to never fail the daily run: every failure mode here is caught and logged,
never raised.

ZERO HUMAN REVIEW BY DESIGN. This is meant to run entirely unattended on
the VPS -- nobody looks at a batch before it reaches the live branch the
production pipeline pulls from. That is a deliberate, explicit choice
(confirmed after being warned of the risk), not an oversight. Given that,
the system prompt below is the *only* guardrail between "the model did
some web research" and "an unverified, possibly sensitive claim about a
real person reaches a monetized, unattended-upload channel." It compiles
every content/tone/sourcing rule this project has used, restated as
faithfully as possible to the original wording. It also uses the
strongest available model at maximum effort specifically because there is
no second check afterward.

This module does add one layer of *mechanical* (non-judgment) validation
after the research call: does each candidate have the right shape, is it
not a duplicate of something already in the pool, and does its
wikipedia_title/section actually resolve via the exact function the
runtime pipeline uses (fetch_wikipedia_extract)? That's schema/reachability
validation, not content review -- it doesn't second-guess whether a claim
is accurate, whether a rumor is hedged correctly, or whether a source
really supports what the model says it supports. Only a human (or a
separate, deliberate review pass) can do that, and this system was built
specifically to run without one.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from config import PIPELINE_DIR, REPO_ROOT

sys.path.insert(0, str(PIPELINE_DIR))

load_dotenv(REPO_ROOT / ".env")

ALMOST_MOVIES_TOPICS_FILE = PIPELINE_DIR / "almost_movies_topics.py"

MIN_THRESHOLD = 6
THRESHOLD_FRACTION = 0.10
REFILL_BATCH_SIZE = 50
REFILL_MODEL = "claude-opus-5"  # strongest available model -- no second check runs after this
MAX_PAUSE_RESTARTS = 8
WIKIPEDIA_VERIFY_DELAY_SECONDS = 2.0

VALID_TYPES = {"collapsed", "conspiracy", "disaster"}
REQUIRED_KEYS = {"type", "name", "wikipedia_title", "section", "hero_concept", "scene_descriptions"}


# ---------------------------------------------------------------------------
# Threshold detection
# ---------------------------------------------------------------------------


def _pool_sizes_and_names() -> dict:
    """Import almost_movies_topics fresh (not cached) so this always
    reflects the file on disk right now."""
    import importlib

    import almost_movies_topics as amt

    importlib.reload(amt)
    return {
        "collapsed": [f["name"] for f in amt.COLLAPSED_ENTRIES],
        "conspiracy": [f["name"] for f in amt.CONSPIRACY_ENTRIES],
        "disaster": [f["name"] for f in amt.DISASTER_ENTRIES],
    }, amt


def refill_threshold(pool_size: int) -> int:
    """6, or 10% of the pool's current size, whichever is higher."""
    return max(MIN_THRESHOLD, -(-pool_size * 10 // 100))  # ceil(pool_size * 0.10)


def _load_rotation_state(amt) -> dict:
    if amt.FILMS_STATE_FILE.exists():
        try:
            return json.loads(amt.FILMS_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def remaining_undrawn(pool_key: str, pool_size: int, state: dict) -> int:
    """How many entries are left before this pool's current shuffle cycle
    exhausts and reshuffles. A pool with no rotation state yet is treated
    as fully fresh (nothing has been drawn from the current cycle)."""
    pool_state = state.get(pool_key) or {}
    order = pool_state.get("order") or []
    position = pool_state.get("position", 0)
    if not order:
        return pool_size
    return max(0, len(order) - position)


def pools_needing_refill() -> dict:
    """Returns {pool_key: {"remaining": int, "threshold": int, "size": int}}
    for every pool at or below its own threshold."""
    names_by_pool, amt = _pool_sizes_and_names()
    state = _load_rotation_state(amt)
    needing = {}
    for pool_key, names in names_by_pool.items():
        size = len(names)
        threshold = refill_threshold(size)
        remaining = remaining_undrawn(pool_key, size, state)
        if remaining <= threshold:
            needing[pool_key] = {"remaining": remaining, "threshold": threshold, "size": size}
    return needing


# ---------------------------------------------------------------------------
# System prompt -- every content/tone/sourcing rule from every prior manual
# batch, restated as faithfully to the original wording as possible.
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """You are researching and verifying new entries for an automated pipeline that
turns obscure, dark, or little-known real movie facts into short-form video
scripts. This batch runs with ZERO human review before publication -- your
research and verification here is the only check that will ever happen
before a claim goes out on a real, monetized YouTube channel. Treat every
claim with the rigor you would want applied before something is published
under your own name with no editor.

GOAL: produce approximately {batch_size} new entries, distributed across
three types (defined below), prioritizing whichever type(s) are listed as
currently depleted, while still contributing a reasonable number to the
others so no pool starves:

{pool_status}

Existing entries already in the pool (do NOT propose any of these again,
and do not propose a different angle on the exact same production/incident
already covered by one of them):
{existing_names}

=== THE THREE TYPES ===

"collapsed": A real, well-documented movie that came shockingly close to
being made (cast attached, sets or costumes already in progress, a director
signed on, a script commissioned) before it collapsed. It must have never
actually been released.

"conspiracy": A persistent, long-circulating rumor, urban legend, or
conspiracy theory connected to a real film. The theory itself must be
something that is genuinely reported/circulated as a rumor or belief --
never something you are inventing or reframing as a rumor. If the real
source material also explains or debunks the rumor, that's fine and often
better (a mundane real explanation makes a satisfying finish).

"disaster": A real movie that WAS completed and released, but had a
chaotic, dangerous, or bizarre production. The hook is the making-of chaos,
never a "this was never made" framing -- that would be factually wrong for
a released film.

=== SOURCING RULES (verbatim from this project's established discipline) ===

- Not limited to Wikipedia. Real film journalism (Empire, Variety, THR,
  IndieWire, Vulture, SlashFilm/Film, Collider, Den of Geek), and citations
  of film-history books or podcast discussions are all acceptable -- but
  only where you can find an actual accessible article, excerpt, or review
  reporting the specific claim, not just knowing a publication or author
  exists and guessing what they might have said.
- Every entry needs a real, checkable URL you actually found via the
  web_search tool, not a source you are inferring should exist.
- If a fact is something you believe is "the kind of thing" a given outlet
  or book would cover, but you cannot find the actual piece reporting it,
  DROP the entry. Do not reconstruct or approximate what a source
  "probably" said.
- Flag and skip clickbait listicle sites that just repeat unverified
  rumors without original reporting.
- You are allowed to use hedging language like "apparently" for minor
  peripheral details without exhaustively cross-verifying every single
  detail from multiple sources -- but this loosens verification DEPTH on
  minor specifics only. It never loosens the core requirement that a real,
  found source exists for the central claim of the entry.

=== THE SINGLE MOST IMPORTANT SOURCING RULE, LEARNED THE HARD WAY ===

The runtime pipeline that actually uses these entries grounds every script
EXCLUSIVELY on Wikipedia -- it fetches only from the `wikipedia_title` (and
`section`, if given) you provide, never from any other source you cite
during research. Non-Wikipedia journalism can inform your research and
build your confidence that a claim is real, but it is NOT sufficient by
itself. For every candidate entry, you must independently confirm, using
web_search or by reasoning about what you already found:
  1. The Wikipedia article at `wikipedia_title` actually exists.
  2. If you specify a `section`, that exact section heading exists on that
     article AND the claim you are grounding the entry on is actually
     contained within that section's own text -- not implied by the
     article in general, not stated in a different section.
This project has previously had to drop entries with strong non-Wikipedia
sourcing (magazine features, film-history books) specifically because the
same claim did not actually appear anywhere in the corresponding Wikipedia
article. If you cannot find the claim in actual Wikipedia article text,
DROP the entry rather than propose it anyway.

Separately: a real bug in this pipeline (now fixed) let the grounding text
bleed from your chosen section into the section immediately following it
on the page, in cases where a wildly different, unrelated fact sat right
next to the intended one. Prefer a `section` where the specific claim you
are grounding sits clearly within that section's own content, not near its
very end where it might read as continuing into whatever comes next.

=== CONTENT RULES (verbatim from this project's established discipline) ===

- No sensationalizing real people's real deaths or tragedies as the hook.
- "conspiracy" type entries: the theory itself must be genuinely
  reported/circulated as a rumor in your sources -- report it as a rumor
  throughout your entry's framing, never state its content as established
  fact.
- No claims about a living person's private motives or behavior unless
  directly, verifiably sourced.
- `hero_concept` and each `scene_descriptions` entry must describe
  costumes/sets/props/concept/mood only -- describe a generic visual
  concept (e.g. "a masked figure in a doorway," "a director on a
  half-built set"), never a specific real actor's likeness, and never
  something that would require reproducing a real leaked photo or
  production still. These fields feed an image generator that is
  separately instructed to invent original imagery from your description
  alone -- so describe the SCENE, not "a photo of [real person]."
- Nothing that's common knowledge or already very well covered by
  mainstream entertainment media (no more Batgirl/Justice League-tier
  stories -- audiences already know those). Go for genuinely obscure,
  dark, or little-known.
- "disaster" type: the film must have actually been completed and
  released. Do not claim or imply cancellation.
- "collapsed" type: the film must have genuinely never been released in
  any form.

=== OUTPUT FORMAT ===

Do your research using the web_search tool. Take as many searches as you
need -- there is no penalty for a long research process, only for a
rushed, unverified one. When you have finished, end your final response
with a single fenced code block containing ONLY a valid JSON array, and
nothing after it. Each element must be an object with exactly these keys:

- "type": one of "collapsed", "conspiracy", "disaster"
- "name": the film's title, exactly as it should appear (e.g. "Heaven's Gate")
- "wikipedia_title": the exact Wikipedia article title to ground on
- "section": the exact section heading text to anchor within that article,
  or null if grounding on the top of the article is appropriate
- "hero_concept": one sentence, a dramatic visual concept for a poster-style
  opening shot (concept/costume/setting only, per the content rules above)
- "scene_descriptions": an array of exactly 6 short visual descriptions
  (concept/costume/setting only, per the content rules above), each tied to
  a specific, real, verified detail from your research

Every entry in your final JSON array must be one you have personally
verified against a real source during this research session. Quality over
quantity: if you can only verify 30 solid entries instead of {batch_size},
output 30. Never pad the list with anything you were not able to verify.
"""


def _build_system_prompt(pool_status: dict, existing_names: dict) -> str:
    status_lines = []
    for pool_key in ("collapsed", "conspiracy", "disaster"):
        info = pool_status.get(pool_key)
        if info:
            status_lines.append(
                f"- {pool_key}: {info['size']} entries, {info['remaining']} undrawn "
                f"remaining (threshold {info['threshold']}) -- DEPLETED, prioritize this type"
            )
        else:
            status_lines.append(f"- {pool_key}: healthy, not depleted")

    names_lines = []
    for pool_key in ("collapsed", "conspiracy", "disaster"):
        names = existing_names.get(pool_key, [])
        names_lines.append(f"{pool_key}: " + ", ".join(names))

    return _SYSTEM_PROMPT_TEMPLATE.format(
        batch_size=REFILL_BATCH_SIZE,
        pool_status="\n".join(status_lines),
        existing_names="\n".join(names_lines),
    )


# ---------------------------------------------------------------------------
# The research call itself
# ---------------------------------------------------------------------------


def _extract_json_array(text: str) -> list:
    fenced = re.findall(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced[-1])
    # Fallback: last top-level [...] in the text.
    matches = re.findall(r"\[[\s\S]*\]", text)
    if not matches:
        raise ValueError("No JSON array found in the model's final response.")
    return json.loads(matches[-1])


def run_refill_research(pool_status: dict, existing_names: dict) -> list:
    """Calls the Anthropic API with the web search tool to research and
    propose new entries. Returns the raw parsed JSON list (not yet
    mechanically verified). Raises on any API/parsing failure -- the
    caller (maybe_refill_pool) is responsible for catching this."""
    client = anthropic.Anthropic()
    system_prompt = _build_system_prompt(pool_status, existing_names)

    user_prompt = (
        f"Research and verify approximately {REFILL_BATCH_SIZE} new entries "
        "now, following every rule in your system prompt exactly. Prioritize "
        "the depleted type(s) listed."
    )
    messages = [{"role": "user", "content": user_prompt}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 150}]

    restarts = 0
    final_response = None
    while True:
        with client.messages.stream(
            model=REFILL_MODEL,
            max_tokens=64000,
            system=system_prompt,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": "max"},
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        final_response = response
        if response.stop_reason != "pause_turn":
            break
        restarts += 1
        if restarts > MAX_PAUSE_RESTARTS:
            raise RuntimeError(
                f"Research turn still paused after {MAX_PAUSE_RESTARTS} restarts -- giving up."
            )
        messages = [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": response.content},
        ]

    if final_response.stop_reason == "refusal":
        raise RuntimeError("Anthropic API refused the refill research request.")

    final_text = "\n".join(b.text for b in final_response.content if b.type == "text")
    if not final_text.strip():
        raise RuntimeError("Research call ended with no text content to parse.")

    return _extract_json_array(final_text)


# ---------------------------------------------------------------------------
# Mechanical (non-judgment) verification
# ---------------------------------------------------------------------------


def _schema_errors(candidate: dict) -> list:
    errors = []
    missing = REQUIRED_KEYS - candidate.keys()
    if missing:
        errors.append(f"missing keys: {sorted(missing)}")
        return errors  # can't check further without the keys

    if candidate["type"] not in VALID_TYPES:
        errors.append(f"invalid type {candidate['type']!r}")
    for key in ("name", "wikipedia_title", "hero_concept"):
        if not isinstance(candidate[key], str) or not candidate[key].strip():
            errors.append(f"{key!r} must be a non-empty string")
    if candidate["section"] is not None and (
        not isinstance(candidate["section"], str) or not candidate["section"].strip()
    ):
        errors.append("'section' must be null or a non-empty string")
    descs = candidate.get("scene_descriptions")
    if not isinstance(descs, list) or len(descs) != 6 or not all(
        isinstance(d, str) and d.strip() for d in descs
    ):
        errors.append("'scene_descriptions' must be a list of exactly 6 non-empty strings")
    return errors


def verify_candidates(candidates: list, amt, existing_names_lower: set) -> tuple[list, list]:
    """Returns (accepted, rejected) where rejected is a list of
    (candidate, reason) pairs. Never raises for an individual bad
    candidate -- one bad entry shouldn't sink the whole batch."""
    accepted = []
    rejected = []
    seen_this_batch = set()

    for candidate in candidates:
        errors = _schema_errors(candidate)
        if errors:
            rejected.append((candidate, "; ".join(errors)))
            continue

        name_lower = candidate["name"].strip().lower()
        if name_lower in existing_names_lower:
            rejected.append((candidate, "duplicate of an existing pool entry"))
            continue
        if name_lower in seen_this_batch:
            rejected.append((candidate, "duplicate within this same batch"))
            continue

        try:
            article = amt.fetch_wikipedia_extract(
                candidate["wikipedia_title"], section=candidate.get("section")
            )
        except Exception as err:  # noqa: BLE001 -- any failure here means "can't verify, reject"
            rejected.append((candidate, f"grounding fetch raised {err!r}"))
            time.sleep(WIKIPEDIA_VERIFY_DELAY_SECONDS)
            continue

        time.sleep(WIKIPEDIA_VERIFY_DELAY_SECONDS)
        if not article:
            rejected.append(
                (candidate, "wikipedia_title/section did not resolve via fetch_wikipedia_extract")
            )
            continue

        seen_this_batch.add(name_lower)
        accepted.append(candidate)

    return accepted, rejected


# ---------------------------------------------------------------------------
# Appending to almost_movies_topics.py
# ---------------------------------------------------------------------------


def _render_entry(entry: dict) -> str:
    def q(s: str) -> str:
        return json.dumps(s)  # reuses JSON's string-escaping; valid Python string literal too

    section = "None" if entry["section"] is None else q(entry["section"])
    scene_lines = "\n".join(f"            {q(d)}," for d in entry["scene_descriptions"])
    return (
        "    {\n"
        f'        "type": {q(entry["type"])},\n'
        f'        "name": {q(entry["name"])},\n'
        f'        "wikipedia_title": {q(entry["wikipedia_title"])},\n'
        f'        "section": {section},\n'
        f'        "hero_concept": {q(entry["hero_concept"])},\n'
        '        "scene_descriptions": [\n'
        f"{scene_lines}\n"
        "        ],\n"
        "    },\n"
    )


def append_entries_to_file(entries: list) -> None:
    if not entries:
        return
    text = ALMOST_MOVIES_TOPICS_FILE.read_text(encoding="utf-8")
    marker = "\n]"
    idx = text.index("FILMS = [")
    close_idx = text.index(marker, idx)
    rendered = "".join(_render_entry(e) for e in entries)
    new_text = text[:close_idx] + rendered + text[close_idx:]
    ALMOST_MOVIES_TOPICS_FILE.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Self-commit and push
# ---------------------------------------------------------------------------


def _git_commit_and_push(accepted: list, rejected_count: int) -> None:
    by_type = {}
    for e in accepted:
        by_type.setdefault(e["type"], []).append(e["name"])
    summary_lines = [f"{t}: {len(names)}" for t, names in sorted(by_type.items())]

    message = (
        f"Auto-refill: add {len(accepted)} researched pool entries "
        f"({', '.join(summary_lines)})\n\n"
        "Autonomous batch via auto_refill_pool.py: researched and verified "
        "with the Anthropic API's web search tool, zero human review by "
        "design. Every entry passed schema validation, duplicate checking, "
        "and live Wikipedia grounding resolution before being added.\n"
    )
    if rejected_count:
        message += f"\n{rejected_count} candidate(s) from this same batch failed mechanical verification and were dropped.\n"
    message += "\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"

    subprocess.run(
        ["git", "add", str(ALMOST_MOVIES_TOPICS_FILE)], cwd=str(REPO_ROOT), check=True
    )
    subprocess.run(
        ["git", "commit", "-m", message], cwd=str(REPO_ROOT), check=True
    )
    subprocess.run(["git", "push"], cwd=str(REPO_ROOT), check=True)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def maybe_refill_pool() -> dict:
    """Checks thresholds and runs a full refill if needed. Never raises --
    every failure is caught and returned in the result dict's 'error' key
    so run_daily.py can log it without failing the day's run."""
    try:
        needing = pools_needing_refill()
        if not needing:
            return {"status": "skipped", "reason": "no pool below threshold"}

        names_by_pool, amt = _pool_sizes_and_names()
        existing_names_lower = {
            n.lower() for names in names_by_pool.values() for n in names
        }

        candidates = run_refill_research(needing, names_by_pool)
        accepted, rejected = verify_candidates(candidates, amt, existing_names_lower)

        if not accepted:
            return {
                "status": "no_accepted_entries",
                "candidates_returned": len(candidates),
                "rejected": [(c.get("name", "?"), reason) for c, reason in rejected],
            }

        append_entries_to_file(accepted)
        _git_commit_and_push(accepted, len(rejected))

        return {
            "status": "refilled",
            "triggered_by": list(needing.keys()),
            "accepted": [e["name"] for e in accepted],
            "rejected": [(c.get("name", "?"), reason) for c, reason in rejected],
        }
    except Exception as err:  # noqa: BLE001 -- must never propagate into run_daily.py
        return {"status": "error", "error": repr(err)}


if __name__ == "__main__":
    result = maybe_refill_pool()
    print(json.dumps(result, indent=2, default=str))
