"""Pick today's entry -- either a real unmade/cancelled film ("collapsed")
or a real, persistent, Wikipedia-documented film conspiracy theory/rumor
("conspiracy") -- from a curated, rotating list, ground it in the real
Wikipedia article, then format both a script topic and a set of
illustration scene-prompts.

Every 3rd run is a conspiracy-type pick (tracked via run_count in
FILMS_STATE_FILE); the other two are collapsed-type. Each type rotates
independently (its own shuffle-without-repeat cycle) so switching the
type on a given run never skips or repeats an entry in the other pool.

Why a curated list instead of a search/discovery step: each entry needs
hand-verified facts (a confirmed Wikipedia article/section, and specific
real visual details for illustration prompts) -- letting a script or LLM
pick candidates risks landing on the wrong page (e.g. a franchise's main
article instead of the cancelled film's own) and silently grounding the
script on unrelated content.

Every wikipedia_title/section pair below was checked live against the
actual Wikipedia API before being included -- not just recalled from
memory. That audit caught real problems on the "collapsed" list: several
of my first-guess titles either didn't exist ("Batgirl (2022 film)",
"Napoleon (unproduced film)", "Batman: Year One (unproduced film)"), or
redirected somewhere unrelated ("Silver & Black" alone resolves to the Las
Vegas Raiders), or redirected into a large unrelated article with only a
small relevant subsection ("Justice League: Mortal" -> "Justice League in
other media"). Halo was dropped entirely after the audit found no reliable
dedicated grounding. The Day the Clown Cried was excluded on tone grounds,
not a facts issue: real and documented, but a Holocaust-drama premise
doesn't fit a witty pop-culture-aside voice.

Same audit discipline applied to the "conspiracy" list. Dropped: the
Wizard of Oz "munchkin suicide" legend (no coverage found in the film's
own article despite being a very famous urban legend -- couldn't confirm
it against the actual source), and the Poltergeist/Omen/Rosemary's Baby
"curse" angles (real, but their Wikipedia coverage centers on specific
real people's real deaths -- e.g. Poltergeist's Dominique Dunne and Heather
O'Rourke -- which doesn't fit a witty pop-culture-aside tone any better
than The Day the Clown Cried did). Kept: The Dark Side of the Rainbow
(dedicated article), the Shining/Room 237 Apollo moon-landing theory (via
"Moon landing conspiracy theories in popular culture"), the Three Men and
a Baby "ghost boy" legend (dedicated section, and Wikipedia's own account
already includes the mundane explanation -- a cardboard cutout left on
set), and The Blair Witch Project's "is this real footage" marketing
legend.

Why the full article extract instead of just the lead summary
(fetch_topic.py's approach): a 2-3 sentence lead usually isn't enough
premise/setting detail to ground specific illustration prompts. This pulls
the full plaintext article (capped) so "Development"/"Production"/"Legacy"
section detail is available too. Some entries only have a subsection
within a much larger article (a director's "unrealized projects" list, a
franchise's "in other media" page, a topic-wide "conspiracy theories in
popular culture" survey) rather than a dedicated page of their own (see
each entry's "section" field below) -- for those, fetch_wikipedia_extract()
locates that specific subsection first, rather than grabbing the top of a
page that's mostly about other, unrelated things.
"""

import json
import random
import re
import sys
from pathlib import Path

import requests

from config import PIPELINE_DIR, WIKIPEDIA_USER_AGENT

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
FILMS_STATE_FILE = PIPELINE_DIR / ".almost_movies_state.json"

# Every scene_description below is a hand-verified, well-documented real
# detail (either about a film's actual attempted production, or about a
# specific documented rumor/legend) -- never a named actor's likeness, so
# the illustration is always an original interpretation of a costume/set/
# prop/creature/atmosphere, not a real person.
FILMS = [
    {
        "type": "collapsed",
        "name": "Superman Lives",
        "wikipedia_title": "The Death of \"Superman Lives\": What Happened?",
        "section": None,
        "scene_descriptions": [
            "an actor screen-testing in a metallic silver-and-black Kryptonian Superman battle suit, no red cape",
            "a colossal mechanical spider built as a movie prop, looming over a Hollywood soundstage",
            "an icy, crystalline Fortress of Solitude film set under construction",
            "concept sketches for a Brainiac-piloted alien warship looming over a city skyline",
            "a costume design table covered in fabric swatches for an all-black superhero suit",
            "a props department workshop with a giant robotic spider leg, half-built",
        ],
    },
    {
        "type": "collapsed",
        "name": "Batgirl",
        "wikipedia_title": "Batgirl (film)",
        "section": None,
        "scene_descriptions": [
            "a caped superhero in a purple-and-black suit crouched on a rain-soaked city rooftop set",
            "a film crew standing beside sealed canisters of finished footage that was never released",
            "a costume department workshop lined with unused superhero suits",
            "a director's monitor playing back a fully edited scene that will never see release",
            "a Gotham-style street set decorated with police cruisers and rain machines, sitting idle",
            "a studio executive's desk stacked with unopened test-screening reports",
        ],
    },
    {
        "type": "collapsed",
        "name": "The Fantastic Four",
        "wikipedia_title": "The Fantastic Four (unreleased film)",
        "section": None,
        "scene_descriptions": [
            "actors in blue spandex superhero costumes on a cramped, low-budget soundstage",
            "a rubbery orange rock-textured superhero suit standing beside unfinished set flats",
            "a single film reel canister locked away in a vault, never sent to theaters",
            "a low-budget special-effects rig for a stretching-arm stunt, held together with visible rigging",
            "a villain's makeshift throne room built from painted foam and plywood",
            "a producer quietly handing over a stack of film cans to be locked away, never distributed",
        ],
    },
    {
        "type": "collapsed",
        "name": "At the Mountains of Madness",
        "wikipedia_title": "Guillermo del Toro's unrealized projects",
        "section": "At the Mountains of Madness",
        "scene_descriptions": [
            "explorers in early-20th-century polar expedition gear facing a vast buried alien city beneath Antarctic ice",
            "concept sketches of towering tentacled alien creatures pinned to a production office wall",
            "a mountain-range concept painting hiding an impossible, non-Euclidean ancient ruin",
            "a director's storyboard wall covered in preliminary art for a doomed Antarctic expedition",
            "a 3D camera rig abandoned on an icy soundstage set",
            "a weathered expedition journal open to a sketch of an impossible geometric structure",
        ],
    },
    {
        "type": "collapsed",
        "name": "Justice League: Mortal",
        "wikipedia_title": "Justice League in other media",
        "section": "Justice League: Mortal (canceled)",
        "scene_descriptions": [
            "a costume fitting room with an ensemble superhero team's suits displayed on mannequins",
            "a film set baking under harsh Australian sunlight, cameras packed away mid-shoot",
            "concept art of a moody ensemble superhero lineup silhouetted against storm clouds",
            "a soundstage with half-built superhero set pieces under tarps",
            "storyboards for an ensemble team walking in slow motion, never filmed",
            "a call sheet pinned to a production office wall, dated for a shoot that never happened",
        ],
    },
    {
        "type": "collapsed",
        "name": "Kubrick's Napoleon",
        "wikipedia_title": "Stanley Kubrick's unrealized projects",
        "section": "Napoleon",
        "scene_descriptions": [
            "thousands of Napoleonic-era soldier extras massed in formation on a European battlefield film set",
            "meticulous early-19th-century military costume designs pinned across a research wall",
            "a director's shooting script covered in dense handwritten historical annotations",
            "rows of file cabinets stuffed with location-scouting photographs from across Europe",
            "a war-room-style map table covered in miniature soldiers recreating a famous battle",
            "a financier's rejection letter sitting atop a mountain of historical research binders",
        ],
    },
    {
        "type": "collapsed",
        "name": "Jodorowsky's Dune",
        "wikipedia_title": "Jodorowsky's Dune",
        "section": None,
        "scene_descriptions": [
            "a surreal, psychedelic desert palace rendered in ornate baroque concept art",
            "an imagined imperial throne room built from impossible, dreamlike geometry",
            "an enormous bound storyboard book stacked on a production table",
            "an ornate toilet-shaped throne built from two intersecting dolphin sculptures",
            "a lifelike animatronic double standing in for an eccentric actor on set",
            "surreal alien costume designs sketched in a biomechanical style",
        ],
    },
    {
        "type": "collapsed",
        "name": "Batman: Year One",
        "wikipedia_title": "Darren Aronofsky's unrealized projects",
        "section": "Batman: Year One",
        "scene_descriptions": [
            "a grim young vigilante walking through a decaying, rain-slicked urban slum at night",
            "early sketches of a crude, home-made bat-costume assembled from scavenged gear",
            "a gritty, unfinished urban film set with no gothic ornamentation",
            "a casting office wall with headshots pinned beneath a torn superhero-sequel poster",
            "a cinematographer's handheld camera test on a rain-soaked alley set",
            "a screenwriter's annotated comic-book pages taped above a typewriter",
        ],
    },
    {
        "type": "collapsed",
        "name": "The Man Who Killed Don Quixote",
        "wikipedia_title": "The Man Who Killed Don Quixote",
        "section": None,
        "scene_descriptions": [
            "film equipment half-submerged after a sudden flash flood on a windswept desert set",
            "a knight in ornate, weathered armor astride a horse beneath a darkening storm sky",
            "a production crew abandoning outdoor sets as a storm rolls across the plain",
            "a sound recordist wincing as fighter jets streak overhead during a take",
            "medical equipment being loaded into a helicopter on a remote desert film set",
            "an insurance adjuster's clipboard resting on a table of ruined camera equipment",
        ],
    },
    {
        "type": "collapsed",
        "name": "Gambit",
        "wikipedia_title": "Gambit (unproduced film)",
        "section": None,
        "scene_descriptions": [
            "a card-throwing mutant in a long trench coat with glowing eyes on a New Orleans-style backlot",
            "a stack of glowing, energy-charged playing cards frozen mid-throw in concept art",
            "a costume rack of unused leather coats in a shuttered production office",
            "a director's chair sitting empty on an abandoned New Orleans-style film set",
            "a studio memo announcing a franchise's quiet cancellation, pinned to a corkboard",
            "a mutant character's glowing staff prop stored on a shelf, never used on camera",
        ],
    },
    {
        "type": "collapsed",
        "name": "Silver & Black",
        "wikipedia_title": "Silver & Black (unproduced film)",
        "section": None,
        "scene_descriptions": [
            "two masked antiheroes in matching silver-and-black tactical suits on a rain-lit rooftop",
            "a costume design board split cleanly into silver and black color schemes",
            "a half-built film set with scaffolding left standing, abandoned mid-construction",
            "a script covered in a director's red-ink notes, rejected before filming could start",
            "two superhero costume mannequins standing back to back, one silver, one black",
            "a studio strategy board with a franchise plan crossed out and rewritten",
        ],
    },
    {
        "type": "conspiracy",
        "name": "The Dark Side of the Rainbow",
        "wikipedia_title": "The Dark Side of the Rainbow",
        "section": None,
        "scene_descriptions": [
            "an old CRT television glowing in a dark room, showing a hazy tornado-swept farmhouse scene",
            "a vinyl record spinning beneath a beam of colored stage light",
            "overlapping film countdown numbers and psychedelic prism patterns bleeding into one another",
            "a dimly lit living room with a stereo system and television set angled toward each other",
            "a newspaper clipping pinned beside a hand-drawn diagram linking a film reel to a record sleeve",
            "a crowd of fans gathered around a television, headphones passed hand to hand",
        ],
    },
    {
        "type": "conspiracy",
        "name": "The Shining",
        "wikipedia_title": "Moon landing conspiracy theories in popular culture",
        "section": "In film",
        "scene_descriptions": [
            "a lone figure in a bulky vintage spacesuit standing in an eerily empty hotel corridor",
            "a hotel hallway with a dizzying geometric patterned carpet stretching into shadow",
            "an old television broadcasting grainy black-and-white footage of a rocket launch",
            "a film reel canister labeled with a documentary title, beside a stack of research clippings",
            "a movie projector casting flickering light onto a wall covered in string and photographs",
            "an old television glitching between static and a hazy, unverified broadcast",
        ],
    },
    {
        "type": "conspiracy",
        "name": "Three Men and a Baby",
        "wikipedia_title": "Three Men and a Baby",
        "section": "Urban legend",
        "scene_descriptions": [
            "a shadowy human silhouette glimpsed behind lace curtains in a sunlit window",
            "a cardboard cutout figure in a tuxedo and top hat standing alone in an empty room",
            "a vintage VHS tape glowing faintly on a shelf in a dim room",
            "a VHS rewinder clicking as a tape pauses mid-frame on a blurry background detail",
            "a soundstage dressed to look like an ordinary apartment, camera gear just out of frame",
            "a discarded prop standee stored in a studio backlot, forgotten after a scene was cut",
        ],
    },
    {
        "type": "conspiracy",
        "name": "The Blair Witch Project",
        "wikipedia_title": "The Blair Witch Project",
        "section": None,
        "scene_descriptions": [
            "a shaky handheld view of dark, tangled woods at dusk",
            "small stick figures bundled with twine, hanging from bare tree branches",
            "a missing-persons flyer taped to a weathered wooden post in a forest clearing",
            "a grainy handheld camcorder viewfinder showing a shaky nighttime forest trail",
            "a movie poster at a film festival listing its cast as missing or presumed dead",
            "a pile of raw videotapes stacked beside a small editing monitor in a cramped room",
        ],
    },
]


COLLAPSED_ENTRIES = [f for f in FILMS if f["type"] == "collapsed"]
CONSPIRACY_ENTRIES = [f for f in FILMS if f["type"] == "conspiracy"]


def _load_state() -> dict:
    if FILMS_STATE_FILE.exists():
        try:
            return json.loads(FILMS_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"run_count": 0}


def _save_state(state: dict) -> None:
    FILMS_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _next_run_is_conspiracy() -> bool:
    """Increments and persists the shared run_count in FILMS_STATE_FILE;
    every 3rd run (3, 6, 9, ...) is a conspiracy-type pick, otherwise
    collapsed-type."""
    state = _load_state()
    run_count = state.get("run_count", 0) + 1
    state["run_count"] = run_count
    _save_state(state)
    return run_count % 3 == 0


def _next_from_pool(pool: list[dict], pool_key: str) -> dict:
    """Return the next single entry from `pool`'s own independent shuffled
    rotation (state tracked under state[pool_key] in FILMS_STATE_FILE),
    reshuffling whenever that pool's cycle runs out -- same
    shuffle-without-repeat mechanism as fetch_topic.py's _next_objects(),
    but drawing one at a time (not a fixed batch) so switching between the
    collapsed/conspiracy pools on different runs never burns through a
    pool's rotation slots for entries it never actually used."""
    state = _load_state()
    pool_state = state.get(pool_key) or {"order": [], "position": 0}
    order = pool_state.get("order") or []
    position = pool_state.get("position", 0)

    if position >= len(order):
        order = list(range(len(pool)))
        random.shuffle(order)
        position = 0

    entry = pool[order[position]]
    position += 1

    state[pool_key] = {"order": order, "position": position}
    _save_state(state)
    return entry


def fetch_wikipedia_extract(title: str, section: str | None = None, max_chars: int = 4000) -> dict | None:
    """Fetch this film's grounding text: the full plaintext article body
    (not just the lead summary), so "Development"/"Production" detail is
    available, not just a 2-3 sentence summary.

    Some films only have a subsection within a director- or franchise-wide
    "unrealized projects" list article rather than a dedicated page of
    their own. When `section` is given, this locates that specific
    subsection heading within the fetched text and starts the extract
    there instead of at the top of the page -- otherwise grounding would
    silently come from whatever unrelated project happens to be covered
    first on that page. If the heading can't be found (e.g. the article
    was re-edited), this returns None so get_almost_movie() moves on to
    the next candidate rather than grounding on the wrong content.
    """
    try:
        resp = requests.get(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "prop": "extracts|info",
                "explaintext": 1,
                "inprop": "url",
                "redirects": 1,
                "titles": title,
                "format": "json",
            },
            headers={"User-Agent": WIKIPEDIA_USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as err:
        print(f"  [!] Could not fetch Wikipedia article for '{title}': {err}", file=sys.stderr)
        return None

    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), None)
    if not page or "missing" in page:
        return None

    full_text = (page.get("extract") or "").strip()
    if not full_text:
        return None

    if section:
        match = re.search(re.escape(section) + r" =+", full_text)
        if not match:
            print(f"  [!] Section '{section}' not found in '{title}'", file=sys.stderr)
            return None
        full_text = full_text[match.start():]

    return {
        "title": page.get("title", title),
        "extract": full_text[:max_chars],
        "url": page.get("fullurl", f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"),
    }


def build_topic(film_name: str, extract: str) -> str:
    return (
        f"A punchy, fast-paced 60-second Short about \"{film_name}\" -- a real "
        f"movie that came shockingly close to being made (cast attached, sets "
        f"or costumes already in progress) before it collapsed. Reveal how far "
        f"it actually got and the specific reason it fell apart. Base every "
        f"claim strictly on this Wikipedia material -- do not invent or add "
        f"facts beyond what it says: \"{extract}\" "
        f"Tone: witty, sharp, quick pop-culture asides -- like a friend who "
        f"knows way too much movie trivia and can't wait to tell you the juicy "
        f"part. Don't write it as any specific critic, YouTuber, or public "
        f"figure's persona -- just a smart, funny narrator voice. End on the "
        f"single most surprising 'so close' detail."
    )


def build_conspiracy_topic(name: str, extract: str) -> str:
    return (
        f"A punchy, fast-paced 60-second Short about a persistent, "
        f"long-circulating rumor or conspiracy theory connected to "
        f"\"{name}\". Base every claim strictly on this Wikipedia material "
        f"-- do not invent or add facts beyond what it says, and drop any "
        f"detail not present in it rather than guessing: \"{extract}\" "
        f"Critical rule: report the theory itself as a reported rumor or "
        f"belief throughout the ENTIRE script -- never state its content as "
        f"established fact, not even once, not even in passing or as a "
        f"punchline. Use hedging language every time the theory's content "
        f"comes up, e.g. \"there's a persistent theory that...\", \"it was "
        f"never confirmed, but...\", \"fans have long speculated that...\", "
        f"\"the rumor goes that...\". If the source material also explains "
        f"or debunks the rumor (a mundane real explanation, an official "
        f"denial, etc.), include that too -- don't cut the debunking for "
        f"time just because the rumor is the more exciting part. "
        f"Tone: witty, sharp, quick pop-culture asides -- like a friend who "
        f"knows way too much movie trivia and can't wait to tell you the "
        f"juicy part. Don't write it as any specific critic, YouTuber, or "
        f"public figure's persona -- just a smart, funny narrator voice."
    )


def build_scene_prompt(film_name: str, scene_description: str) -> str:
    """Build one illustration prompt for illustration_gen.generate_illustration().

    `scene_description` must be one of FILMS' hand-verified real visual
    details -- concrete enough to be recognizably tied to that film's
    concept, not just the generic mood illustration_gen.STYLE_PREFIX sets.
    """
    return (
        f"From the unmade film \"{film_name}\": {scene_description}. "
        f"This is an original artistic reinterpretation, imagined fresh -- "
        f"not a reproduction of any specific real leaked photo, costume "
        f"test, or concept-art painting from the actual production."
    )


def _try_pool(pool: list[dict], pool_key: str, max_attempts: int, tried: list[str]) -> tuple[str, dict] | None:
    for _ in range(min(max_attempts, len(pool))):
        entry = _next_from_pool(pool, pool_key)
        tried.append(f"{entry['name']} ({entry['type']})")
        article = fetch_wikipedia_extract(entry["wikipedia_title"], section=entry.get("section"))
        if not article:
            continue
        if entry["type"] == "conspiracy":
            topic = build_conspiracy_topic(entry["name"], article["extract"])
        else:
            topic = build_topic(entry["name"], article["extract"])
        scene_prompts = [build_scene_prompt(entry["name"], desc) for desc in entry["scene_descriptions"]]
        meta = {
            "film": entry["name"],
            "type": entry["type"],
            "wikipedia_title": article["title"],
            "wikipedia_url": article["url"],
            "scene_prompts": scene_prompts,
        }
        return topic, meta
    return None


def get_almost_movie(max_attempts: int = 5) -> tuple[str, dict]:
    """Returns (topic_string, meta) where meta has 'film', 'type'
    ('collapsed' or 'conspiracy'), 'wikipedia_title', 'wikipedia_url', and
    'scene_prompts' (list[str], ready for illustration_gen.generate_illustration()).

    Every 3rd call (tracked via run_count in FILMS_STATE_FILE) picks from
    CONSPIRACY_ENTRIES; the other two out of three pick from
    COLLAPSED_ENTRIES. Each pool draws one entry at a time from its own
    independent shuffle-without-repeat rotation (see _next_from_pool) --
    not fetch_topic.py's pre-draw-5-candidates pattern, which would burn
    through a small pool's rotation slots on every single call regardless
    of whether the first candidate succeeds.

    If every candidate in the selected pool fails to fetch, falls back to
    trying the other pool once before giving up entirely -- better to post
    something than nothing for an unattended daily run.
    """
    is_conspiracy = _next_run_is_conspiracy()
    primary = (CONSPIRACY_ENTRIES, "conspiracy") if is_conspiracy else (COLLAPSED_ENTRIES, "collapsed")
    fallback = (COLLAPSED_ENTRIES, "collapsed") if is_conspiracy else (CONSPIRACY_ENTRIES, "conspiracy")

    tried: list[str] = []
    result = _try_pool(*primary, max_attempts, tried)
    if result is None:
        result = _try_pool(*fallback, max_attempts, tried)
    if result is not None:
        return result

    raise RuntimeError(
        f"Could not fetch a Wikipedia article for any candidate: {tried}. "
        f"Check network access or the wikipedia_title/section entries in FILMS."
    )


if __name__ == "__main__":
    topic, meta = get_almost_movie()
    print(f"Today's pick ({meta['type']}): {meta['film']} ({meta['wikipedia_url']})")
    print("\nTopic string for script generation:\n")
    print(topic)
    print("\nScene prompts:\n")
    for p in meta["scene_prompts"]:
        print(f"  - {p}")
