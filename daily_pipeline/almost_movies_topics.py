"""Pick today's entry from a curated, rotating list -- a real unmade/
cancelled film ("collapsed"), a real completed film with a chaotic/
dangerous/bizarre production ("disaster"), or a real, persistent,
Wikipedia-documented film conspiracy theory/rumor ("conspiracy") -- ground
it in the real Wikipedia article, then format both a script topic and a
set of illustration scene-prompts.

Each run (tracked via run_count in FILMS_STATE_FILE) cycles evenly through
collapsed -> conspiracy -> disaster -> collapsed -> ... (see
_next_run_type()). Each type rotates independently (its own
shuffle-without-repeat cycle) so switching the type on a given run never
skips or repeats an entry in another pool.

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
        "hero_concept": "a reimagined Superman in a sleek black-and-silver battle suit, no cape, framed against a shattered Metropolis skyline with a colossal alien spider looming behind him",
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
        "hero_concept": "a caped vigilante in a purple-and-black suit crouched on a rain-soaked Gotham rooftop, city lights blazing below",
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
        "hero_concept": "four costumed heroes in blue silhouetted against a crumbling city skyline, one towering rock-textured figure standing among them",
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
        "hero_concept": "a lone polar explorer dwarfed by a vast, impossible ancient city rising from the Antarctic ice under a blood-red sky",
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
        "hero_concept": "an ensemble of six silhouetted superheroes standing shoulder to shoulder against a stormy Australian sky",
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
        "hero_concept": "a solitary military commander on horseback surveying a vast battlefield of thousands of massed soldiers at dawn",
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
        "hero_concept": "a robed figure standing before a surreal, towering desert palace built from impossible baroque geometry, twin moons overhead",
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
        "hero_concept": "a grim young vigilante in a crude home-made bat-costume silhouetted against a decaying, rain-slicked city skyline",
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
        "hero_concept": "a weathered knight in armor astride a horse against a churning storm-lit desert sky, windmills in the distance",
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
        "hero_concept": "a trench-coated mutant hurling glowing energy-charged playing cards through a rain-soaked New Orleans street at night",
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
        "hero_concept": "two masked antiheroes in matching silver-and-black tactical suits standing back to back atop a rain-lit skyscraper",
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
        "hero_concept": "a tornado-swept farmhouse rendered in prismatic, psychedelic color washes, as if a film reel and a vinyl record collided",
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
        "hero_concept": "a lone figure in a vintage spacesuit standing at the end of an impossibly long, geometrically patterned hotel corridor",
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
        "hero_concept": "a shadowy silhouette behind a lace-curtained window in an ordinary suburban house, bathed in eerie afternoon light",
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
        "hero_concept": "a shaky, grainy view into a dense, twisted forest at dusk, stick figures barely visible hanging from distant branches",
        "scene_descriptions": [
            "a shaky handheld view of dark, tangled woods at dusk",
            "small stick figures bundled with twine, hanging from bare tree branches",
            "a missing-persons flyer taped to a weathered wooden post in a forest clearing",
            "a grainy handheld camcorder viewfinder showing a shaky nighttime forest trail",
            "a movie poster at a film festival listing its cast as missing or presumed dead",
            "a pile of raw videotapes stacked beside a small editing monitor in a cramped room",
        ],
    },
    {
        "type": "collapsed",
        "name": "Terry Gilliam's Watchmen",
        "wikipedia_title": "Terry Gilliam's unrealized projects",
        "section": "Watchmen",
        "hero_concept": "a grim antihero in a soot-stained trench coat standing before a giant ticking clock face under a nuclear-orange sky",
        "scene_descriptions": [
            "a masked vigilante's smiley-face badge, smeared with a single drop of blood, pinned to a worn trench coat",
            "a director's storyboard wall covered in sketches of a shadowy antihero perched on a rain-slicked rooftop",
            "a gritty 1980s New York backlot set, dressed for an alternate Cold War timeline",
            "a giant analog doomsday clock looming over a dimly lit film production office",
            "a costume rack of muted superhero uniforms, deliberately unglamorous and worn-looking",
            "a budget ledger covered in red ink, stacked beside an unfinished shooting script",
        ],
    },
    {
        "type": "collapsed",
        "name": "Ronnie Rocket",
        "wikipedia_title": "Ronnie Rocket",
        "section": None,
        "hero_concept": "a small detective-like figure balanced on one leg amid a smoky industrial landscape of towering smokestacks",
        "scene_descriptions": [
            "a detective in a rumpled suit balancing impossibly on one leg inside a dim, smoke-filled room",
            "a forest of towering industrial smokestacks belching smoke into a dark orange sky",
            "a flickering neon sign advertising a mysterious 'second dimension' above a shadowy doorway",
            "a director's cluttered desk covered in rejected financing letters and hand-drawn sketches",
            "a small red-headed figure silhouetted against a wall of humming electrical equipment",
            "an abandoned film set of a surreal industrial nightclub, dust gathering on unused props",
        ],
    },
    {
        "type": "collapsed",
        "name": "James Cameron's Spider-Man",
        "wikipedia_title": "Spider-Man in film",
        "section": "Feature film development",
        "hero_concept": "a web-slinging hero silhouetted against the twin towers of the World Trade Center at dusk, storm clouds gathering",
        "scene_descriptions": [
            "a masked hero crouched atop a skyscraper ledge, twin towers looming in the smoky skyline behind him",
            "a lightning-charged villain crackling with electricity in a darkened power plant",
            "a producer's desk buried under a stack of legal filings and a thick unproduced script",
            "a hand-typed manuscript page covered in dense red editing marks",
            "two silhouetted figures standing close together on a fog-shrouded suspension bridge at night",
            "a film financier's office, phone off the hook, walls covered in a collapsing production timeline",
        ],
    },
    {
        "type": "collapsed",
        "name": "Leningrad: The 900 Days",
        "wikipedia_title": "Sergio Leone",
        "section": "Leningrad: The 900 Days",
        "hero_concept": "a lone photographer with a vintage camera standing before a besieged wartime city skyline under artillery fire",
        "scene_descriptions": [
            "a war photographer crouched behind rubble, camera raised toward a burning city skyline",
            "rows of tanks and howitzers massed on a snow-covered European battlefield film set",
            "a director's office wall covered in location-scouting photographs from a foreign city",
            "an ornate unsigned contract resting on a director's desk, pen set beside it",
            "a wartime newsreel camera abandoned on a tripod amid smoking rubble",
            "a stack of research books on a WWII siege piled beside a half-finished shooting script",
        ],
    },
    {
        "type": "collapsed",
        "name": "Alien 3 (Vincent Ward's version)",
        "wikipedia_title": "Alien 3",
        "section": "Start-up with Vincent Ward",
        "hero_concept": "a lone astronaut's escape pod crash-landed in the courtyard of a vast wooden monastery on an alien world",
        "scene_descriptions": [
            "a wooden monastery interior, archaic and dim, its wooden beams stretching into shadow",
            "a robed monk staring up in awe at a strange light streaking across a night sky",
            "an escape pod half-buried in the muddy courtyard of an ancient wooden structure",
            "a group of hooded monastic figures gathered in fearful debate beneath flickering torchlight",
            "a shadowy creature glimpsed at the edge of torchlight in a wooden corridor",
            "a director's concept sketch of a religious order confronting an otherworldly omen",
        ],
    },
    {
        "type": "collapsed",
        "name": "Batman Unchained",
        "wikipedia_title": "Batman in film",
        "section": "Unrealized proposals",
        "hero_concept": "a caped figure standing at the mouth of a dark cave as a swarm of bats erupts around him",
        "scene_descriptions": [
            "a lone figure entering a shadowy cave mouth as bats begin to swirl around him",
            "a hallucinatory carnival of masked figures looming over a caped vigilante in a fog-drenched alley",
            "a scarecrow-like figure looming amid drifting toxic gas in an abandoned warehouse",
            "a swarm of bats erupting from a cave into a moonlit tropical sky",
            "a costume department sketch of a caped hero's suit, redesigned for a darker tone",
            "a production budget document covered in slashed-out numbers for an expensive finale",
        ],
    },
    {
        "type": "collapsed",
        "name": "Beetlejuice Goes Hawaiian",
        "wikipedia_title": "Beetlejuice Beetlejuice",
        "section": "Development",
        "hero_concept": "a ghoulish trickster in a loud Hawaiian shirt grinning beside a crumbling tiki idol on a moonlit beach",
        "scene_descriptions": [
            "a mischievous striped-suited figure lounging on a tropical beach beside a carved tiki idol",
            "a half-built luxury resort construction site with ominous ancient burial markers half-unearthed",
            "a surfer silhouetted against a swirling German-Expressionist-style stormy sky",
            "a family in tourist attire standing uneasily before a crumbling ancient stone shrine",
            "a production concept sketch blending beach-movie palm trees with jagged expressionist shadows",
            "a director's script covered in tropical-themed margin doodles beside a cancellation memo",
        ],
    },
    {
        "type": "collapsed",
        "name": "Star Trek: The God Thing",
        "wikipedia_title": "Star Trek: The God Thing",
        "section": None,
        "hero_concept": "a starship crew silhouetted against a colossal, god-like entity looming over Earth",
        "scene_descriptions": [
            "a towering, radiant alien entity looming over a small blue planet, arms outstretched",
            "a starship bridge crew staring in stunned silence at a massive glowing figure on the viewscreen",
            "a scattered group of former crewmates reuniting aboard a dimly lit starship corridor",
            "a script cover page stamped 'SHELVED' resting on a studio executive's desk",
            "a starship silhouette dwarfed by an impossibly vast celestial being",
            "a production illustration of Earth's cities looking up in awe and terror at the sky",
        ],
    },
    {
        "type": "collapsed",
        "name": "Speed 3",
        "wikipedia_title": "Speed 2: Cruise Control",
        "section": None,
        "hero_concept": "an action hero sprinting away from a towering ocean liner as it looms impossibly large behind him",
        "scene_descriptions": [
            "an action hero glancing skeptically at a script page describing a slow-moving cruise ship",
            "a massive ocean liner drifting helplessly toward a rocky coastline",
            "a stunt coordinator's whiteboard covered in crossed-out vehicle ideas for a threequel",
            "a producer's office wall lined with poor box-office reports pinned beside a shelved script",
            "an actor's empty director's chair on an abandoned film set gangway",
            "a film reel canister labeled 'Part Three' collecting dust on a high studio shelf",
        ],
    },
    {
        "type": "collapsed",
        "name": "Hitchcock's The Blind Man",
        "wikipedia_title": "Alfred Hitchcock's unrealized projects",
        "section": "The Blind Man (1960)",
        "hero_concept": "a shadowy figure fleeing through a carnival midway, giant amusement-park silhouettes looming behind him",
        "scene_descriptions": [
            "a lone figure sprinting through a carnival midway lit by looming Ferris wheel silhouettes",
            "a carousel spinning eerily empty at night, colored lights reflecting off wet pavement",
            "a director's letter of rejection stamped across a storyboard sketch of a theme park chase",
            "a blind man's cane tapping along a carnival walkway lined with distorted funhouse mirrors",
            "a shadowy pursuer glimpsed between towering amusement park ride structures",
            "a script page for a suspense film sitting unopened on a studio executive's desk",
        ],
    },
    {
        "type": "disaster",
        "name": "Roar",
        "wikipedia_title": "Roar (film)",
        "section": None,
        "hero_concept": "a lone figure frozen mid-step as a pride of real lions and tigers prowl through a sunlit African-style compound",
        "scene_descriptions": [
            "a cinematographer's camera abandoned mid-shot as a lion lunges toward the lens",
            "a sprawling compound overrun by dozens of real lions and tigers roaming freely",
            "a bandaged crew member sitting stunned outside a makeshift on-set medical tent",
            "a family standing frozen in a sunlit den as a tiger paces across the room behind them",
            "a director covered in fresh scratches, still holding a bullhorn on an active film set",
            "a stack of medical release forms fluttering on a table beside a first-aid kit",
        ],
    },
    {
        "type": "disaster",
        "name": "The Island of Dr. Moreau",
        "wikipedia_title": "The Island of Dr. Moreau (1996 film)",
        "section": None,
        "hero_concept": "a grotesque half-human creature standing on a storm-battered tropical shoreline, watching a film set collapse into the sea",
        "scene_descriptions": [
            "a howling tropical storm sweeping an entire film set out into a churning ocean",
            "a grotesque beast-man costume half-finished on a workshop mannequin",
            "a fired director disguised in a creature costume, lingering unnoticed at the edge of a film set",
            "a jungle compound of thatched huts battered by wind and driving rain",
            "a replacement director arriving by boat to a chaotic, storm-wrecked production site",
            "a stack of urgent telegrams piled on a producer's desk, deadlines circled in red",
        ],
    },
    {
        "type": "disaster",
        "name": "Manos: The Hands of Fate",
        "wikipedia_title": "Manos: The Hands of Fate",
        "section": None,
        "hero_concept": "a lone door-to-door salesman standing triumphantly beside an old hand-cranked film camera under a spotlight",
        "scene_descriptions": [
            "a napkin covered in scribbled film-plot notes on a diner coffee-shop table",
            "an old hand-cranked 16mm film camera propped on a tripod in a dusty desert clearing",
            "a rented searchlight sweeping the night sky above a small-town movie theater marquee",
            "a stretch limousine shuttling the same few cast members repeatedly around a city block",
            "a stack of unpaid profit-share contracts fluttering on a folding table",
            "a lone robed figure standing ominously in a desert doorway at dusk",
        ],
    },
    {
        "type": "disaster",
        "name": "Heaven's Gate",
        "wikipedia_title": "Heaven's Gate (film)",
        "section": "Cimino's perfectionism",
        "hero_concept": "a director standing alone on a vast, half-rebuilt Old West street set, staring up at the sky waiting for a single cloud",
        "scene_descriptions": [
            "an entire Old West street set being torn down and rebuilt plank by plank",
            "a vintage steam locomotive being hauled cross-country on the back of a flatbed truck",
            "a director staring skyward, waiting motionless for one particular cloud to drift into frame",
            "a lone tree being uprooted and relocated across an empty film set field",
            "a weary actor packing a suitcase to leave for another film, then returning months later",
            "an assistant director's clipboard covered in tally marks counting fifty identical takes",
        ],
    },
    {
        "type": "disaster",
        "name": "The Texas Chain Saw Massacre",
        "wikipedia_title": "The Texas Chain Saw Massacre",
        "section": "Filming",
        "hero_concept": "a masked figure looming in a sweltering, sun-bleached farmhouse doorway, heat shimmering in the air",
        "scene_descriptions": [
            "a leather-masked figure standing in a doorway, heat haze shimmering around a sun-scorched farmhouse",
            "a lone actor slumped in a folding chair between takes, drenched in sweat under a relentless sun",
            "a single worn costume hanging on a nail, its fabric stained and never replaced",
            "a film crew crowded under a makeshift tent, fanning themselves between exhausting takes",
            "a rural farmhouse set baking under a merciless midday sun, dust rising from a gravel road",
            "a censorship stamp reading BANNED overlaid across a torn foreign film poster",
        ],
    },
    {
        "type": "disaster",
        "name": "Popeye",
        "wikipedia_title": "Popeye (film)",
        "section": "Production",
        "hero_concept": "a scrawny sailor in a striped shirt squinting against the sun on a ramshackle seaside village film set",
        "scene_descriptions": [
            "a boardroom table of studio executives shrugging over a stack of comic-strip licensing folders",
            "a scrawny sailor character standing awkwardly on a ramshackle painted seaside village set",
            "a talent manager's phone call cut short, a worried expression crossing her face",
            "a director's chair sitting empty beside a chaotic multinational film crew on a Mediterranean coastline",
            "a stack of two-picture studio deal contracts stamped with two different studio logos",
            "a weathered seaside village facade under construction on a rocky island coastline",
        ],
    },
    {
        "type": "disaster",
        "name": "The Wages of Fear",
        "wikipedia_title": "The Wages of Fear",
        "section": "Production",
        "hero_concept": "a battered cargo truck teetering on a narrow cliffside road, nitroglycerin drums rattling in its bed",
        "scene_descriptions": [
            "a battered truck creeping along a crumbling mountain dirt road above a steep drop",
            "drums of unstable liquid rattling ominously in the back of a rusted cargo truck",
            "a director on crutches directing a crew from the edge of a dusty film set",
            "a distant oil well fire glowing on the horizon beyond a barren mountain landscape",
            "four weary men studying a hand-drawn map by lantern light in a rundown truck cab",
            "a production ledger covered in red ink, numbers crossed out and rewritten",
        ],
    },
    {
        "type": "disaster",
        "name": "Waterworld",
        "wikipedia_title": "Waterworld",
        "section": "Production",
        "hero_concept": "a lone sailor lashed to the mast of a sinking trimaran as towering waves crash over an endless ocean film set",
        "scene_descriptions": [
            "a lone figure lashed to a ship's mast as churning waves crash over a sinking vessel",
            "an entire floating film set slowly sinking beneath dark ocean waves",
            "a stunt diver vanishing beneath churning water as a safety crew scrambles at the surface",
            "a massive artificial seawater enclosure stretching to the horizon under an overcast sky",
            "a director's chair rocking precariously on a floating platform amid rising swells",
            "a composer's musical score scattered and abandoned on an editing room floor",
        ],
    },
    {
        "type": "disaster",
        "name": "Jaws",
        "wikipedia_title": "Jaws (film)",
        "section": "Filming",
        "hero_concept": "a massive mechanical shark half-submerged and motionless in open water, hidden pneumatic hoses exposed along its flank",
        "scene_descriptions": [
            "a colossal mechanical shark prop lying motionless and waterlogged at the edge of a dock",
            "a tangle of pneumatic hoses and cables snaking along the hidden side of a fake shark",
            "a film crew hauling a massive prop shark out of the water on a long tow line",
            "a director rewriting a script page, crossing out shark scenes one by one",
            "a rusted pneumatic rig half-submerged in salt water, corroded and sinking",
            "a small fishing boat dwarfed by the looming dorsal fin of an unseen predator",
        ],
    },
    {
        "type": "conspiracy",
        "name": "Three Kings",
        "wikipedia_title": "Three Kings (1999 film)",
        "section": "Film techniques",
        "hero_concept": "a rumor-shrouded silhouette of a soldier collapsing as a red tabloid stamp reading EXPOSED looms over the scene",
        "scene_descriptions": [
            "a special-effects prosthetic torso rigged with tubing, prepared for a gunshot effect",
            "a film crew huddled around a monitor reviewing a graphic wound effect playback",
            "a tabloid-style newspaper clipping with a scandalous headline about a war film's realism",
            "a director joking with cast members on set, a raised eyebrow of disbelief nearby",
            "a prop morgue table with a sheet-covered mannequin under harsh studio lighting",
            "a stack of denial statements pinned to a studio bulletin board",
        ],
    },
    {
        "type": "conspiracy",
        "name": "Robert the Doll",
        "wikipedia_title": "Robert (doll)",
        "section": None,
        "hero_concept": "a weathered antique doll sitting alone in a glass museum case, surrounded by stacks of apology letters",
        "scene_descriptions": [
            "a weathered antique sailor doll propped upright in a dusty glass museum display case",
            "a pile of handwritten apology letters addressed to an old doll, stacked on a museum counter",
            "a child's bedroom shelf with an old doll positioned facing the room, unmoving",
            "a museum curator's ledger listing decades of visitor reports beside a doll's photograph",
            "two dolls side by side on a workshop table -- one antique, one plastic and modern",
            "a tabloid clipping with a bold red stamp reading EXPOSED over a photograph of an old doll",
        ],
    },
    {
        "type": "conspiracy",
        "name": "Aladdin's subliminal message",
        "wikipedia_title": "Aladdin (1992 Disney film)",
        "section": "Controversies",
        "hero_concept": "a genie's smoke curling into the shape of a whispered word above a shadowy animated bedroom window",
        "scene_descriptions": [
            "wisps of magical smoke curling into a barely legible whispered phrase above a rooftop",
            "a sound engineer adjusting dials at a mixing board, headphones covering both ears",
            "a film reel spinning in slow motion, a single frame of dialogue circled in red marker",
            "a parent pointing accusingly at a glowing television screen in a dim living room",
            "an animation studio storyboard with a margin note reading 'RE-RECORD THIS LINE'",
            "a tabloid-style clipping stamped BANNED over a colorful animated movie poster fragment",
        ],
    },
]


COLLAPSED_ENTRIES = [f for f in FILMS if f["type"] == "collapsed"]
CONSPIRACY_ENTRIES = [f for f in FILMS if f["type"] == "conspiracy"]
DISASTER_ENTRIES = [f for f in FILMS if f["type"] == "disaster"]

# Round-robin order for _next_run_type() below. Also doubles as the
# fallback-trial order in get_almost_movie() (rotated to start at whichever
# type a given run landed on) -- so the fallback direction is deterministic,
# not just "try the two other pools in whatever order dict iteration gives."
TYPE_ORDER = ["collapsed", "conspiracy", "disaster"]

POOL_BY_TYPE = {
    "collapsed": COLLAPSED_ENTRIES,
    "conspiracy": CONSPIRACY_ENTRIES,
    "disaster": DISASTER_ENTRIES,
}


def _load_state() -> dict:
    if FILMS_STATE_FILE.exists():
        try:
            return json.loads(FILMS_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"run_count": 0}


def _save_state(state: dict) -> None:
    FILMS_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _next_run_type() -> str:
    """Increments and persists the shared run_count in FILMS_STATE_FILE;
    cycles evenly through collapsed -> conspiracy -> disaster -> collapsed
    -> ... (a straight 3-way round robin). Replaces the old "every 3rd run
    is conspiracy, otherwise collapsed" 2:1 split now that there's a third,
    equally legitimate pool -- no reason to weight collapsed twice as
    heavily as either of the other two anymore."""
    state = _load_state()
    run_count = state.get("run_count", 0) + 1
    state["run_count"] = run_count
    _save_state(state)
    return TYPE_ORDER[(run_count - 1) % 3]


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

        # Stop at the next heading (any level) so the extract can't bleed
        # into unrelated later sections of the same article -- verified
        # live: without this, e.g. "Three Kings"' "Film techniques" section
        # ran straight into the next section ("Conflicts") and picked up an
        # unrelated real anecdote, which a compressed script latched onto
        # as its entire subject instead of the section this entry was
        # actually curated for.
        own_heading_end = full_text.find("\n")
        if own_heading_end == -1:
            own_heading_end = len(full_text)
        next_heading = re.search(r"\n[^\n]{1,80} =+\n", full_text[own_heading_end:])
        if next_heading:
            full_text = full_text[: own_heading_end + next_heading.start()]

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


def build_disaster_topic(film_name: str, extract: str) -> str:
    """For films that were actually completed and released, but had a
    chaotic, dangerous, or bizarre production. Deliberately warns the model
    off borrowing build_topic()'s "was this ever made" framing -- the two
    topic types are about adjacent territory (production chaos) with
    opposite outcomes, so an explicit guardrail against the wrong one is
    worth the extra sentence."""
    return (
        f"A punchy, fast-paced 60-second Short about the chaotic, dangerous, "
        f"or bizarre real story behind how \"{film_name}\" actually got made. "
        f"This film WAS completed and released -- do not claim or imply it "
        f"was cancelled or never made. Reveal the single most shocking thing "
        f"that happened during production and how the cast and crew dealt "
        f"with it. Base every claim strictly on this Wikipedia material -- "
        f"do not invent or add facts beyond what it says: \"{extract}\" "
        f"Tone: witty, sharp, quick pop-culture asides -- like a friend who "
        f"knows way too much movie trivia and can't wait to tell you the "
        f"juicy part. Don't write it as any specific critic, YouTuber, or "
        f"public figure's persona -- just a smart, funny narrator voice. End "
        f"on the single most surprising 'how did this actually happen' "
        f"detail."
    )


def build_hero_prompt(film_name: str, hero_concept: str) -> str:
    """Build the poster-style hero-shot prompt for illustration_gen.generate_illustration().

    Unlike build_scene_prompt(), which grounds each image on one specific
    documented production detail, this frames the film's overall concept/
    characters/setting as a single dramatic, cinematic hero image -- the
    shot that opens the video and anchors it. Generated with fal.ai's
    higher-quality Flux Pro model instead of Schnell (see generate_video.py).
    """
    return (
        f"A dramatic, cinematic movie-poster-style hero shot for the film "
        f"\"{film_name}\": {hero_concept}. Bold composition, striking "
        f"lighting, epic movie-poster energy. This is an original artistic "
        f"interpretation, imagined fresh purely from the film's concept, "
        f"characters, and setting -- NOT a reproduction, homage, or "
        f"reinterpretation of any real existing poster, marketing key art, "
        f"or promotional image for this or any other film."
    )


def build_scene_prompt(film_name: str, scene_description: str) -> str:
    """Build one illustration prompt for illustration_gen.generate_illustration().

    `scene_description` must be one of FILMS' hand-verified real visual
    details -- concrete enough to be recognizably tied to that film's
    concept, not just the generic mood illustration_gen.STYLE_PREFIX sets.
    """
    return (
        f"From the film \"{film_name}\": {scene_description}. "
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
        elif entry["type"] == "disaster":
            topic = build_disaster_topic(entry["name"], article["extract"])
        else:
            topic = build_topic(entry["name"], article["extract"])
        scene_prompts = [build_scene_prompt(entry["name"], desc) for desc in entry["scene_descriptions"]]
        hero_prompt = build_hero_prompt(entry["name"], entry["hero_concept"])
        meta = {
            "film": entry["name"],
            "type": entry["type"],
            "wikipedia_title": article["title"],
            "wikipedia_url": article["url"],
            "hero_prompt": hero_prompt,
            "scene_prompts": scene_prompts,
        }
        return topic, meta
    return None


def get_almost_movie(max_attempts: int = 5) -> tuple[str, dict]:
    """Returns (topic_string, meta) where meta has 'film', 'type'
    ('collapsed', 'conspiracy', or 'disaster'), 'wikipedia_title',
    'wikipedia_url', 'hero_prompt' (str, the poster-style opening shot --
    generate with illustration_gen.generate_illustration(..., model="pro")),
    and 'scene_prompts' (list[str], ready for
    illustration_gen.generate_illustration()).

    Each call (tracked via run_count in FILMS_STATE_FILE) cycles evenly
    through collapsed -> conspiracy -> disaster -> collapsed -> ... (see
    _next_run_type()). Each pool draws one entry at a time from its own
    independent shuffle-without-repeat rotation (see _next_from_pool) --
    not fetch_topic.py's pre-draw-5-candidates pattern, which would burn
    through a small pool's rotation slots on every single call regardless
    of whether the first candidate succeeds.

    If every candidate in the selected pool fails to fetch, falls back to
    trying the other two pools (in TYPE_ORDER, starting right after the
    primary type) before giving up entirely -- better to post something
    than nothing for an unattended daily run.
    """
    primary_type = _next_run_type()
    start = TYPE_ORDER.index(primary_type)
    ordered_types = TYPE_ORDER[start:] + TYPE_ORDER[:start]

    tried: list[str] = []
    for type_name in ordered_types:
        result = _try_pool(POOL_BY_TYPE[type_name], type_name, max_attempts, tried)
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
    print("\nHero prompt (Flux Pro):\n")
    print(f"  - {meta['hero_prompt']}")
    print("\nScene prompts (Flux Schnell):\n")
    for p in meta["scene_prompts"]:
        print(f"  - {p}")
