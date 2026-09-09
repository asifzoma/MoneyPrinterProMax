"""Generate concept-art illustrations via fal.ai -- standing in for the
object-history pipeline's real-photo Wikimedia Commons search
(commons_search.py) now that every scene needs to depict something that was
never actually filmed.

One style (STYLE_PREFIX, a pulp tabloid/exposé aesthetic) applied to every
image in a video, rendered by one of two models picked via the `model`
switch: Flux Schnell (fast/cheap, ~$0.003/image) for the bulk of a video's
scene illustrations, and Flux Pro v1.1 (~$0.04/image) for the one hero shot
that opens each video -- higher quality worth the small extra cost for the
shot that anchors the video. That's a cost/quality choice, not a style
split: both models render the same STYLE_PREFIX. Both endpoints share the
same request/response shape (image_size enum in, images[0].url out), so
this is one function with a model switch, not two separate code paths.

Requires FAL_KEY in .env (see .env.example). Get one at https://fal.ai/dashboard/keys.
"""

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

from config import REPO_ROOT

load_dotenv(REPO_ROOT / ".env")
FAL_API_KEY = os.environ.get("FAL_KEY", "")

FAL_ENDPOINTS = {
    "schnell": "https://fal.run/fal-ai/flux/schnell",
    "pro": "https://fal.run/fal-ai/flux-pro/v1.1",
}

STYLE_PREFIX = (
    "Pulp tabloid exposé aesthetic: grainy halftone print texture, "
    "high-contrast black-and-white or sepia tones, rough torn-newspaper "
    "clipping edges, tabloid-headline energy -- like a scandalous "
    "front-page photo from a sensationalist rag. Occasionally overlaid "
    "with a bold red rubber-stamp reading CLASSIFIED, BANNED, or EXPOSED, "
    "angled across the image. Gritty and dramatic, not polished or clean. "
    "This is an original artistic interpretation only: do not depict any "
    "specific real actor's likeness, any real leaked costume photo, or any "
    "real production still -- invent the imagery from the scene "
    "description alone."
)


class IllustrationError(Exception):
    """Raised when fal.ai fails to return a usable image."""


def generate_illustration(
    scene_prompt: str,
    out_dir: Path,
    image_size: str = "portrait_16_9",
    model: str = "schnell",
) -> Path:
    """Generate one concept-art illustration for `scene_prompt` and save it
    under `out_dir`. Returns the local path.

    `scene_prompt` should describe one moment from the film (e.g. "a
    costumed actor standing on a half-built alien city set") -- not
    STYLE_PREFIX, which is prepended here automatically.

    `model` is "schnell" (default, fast/cheap) or "pro" (fal.ai's Flux Pro
    v1.1, higher quality, ~13x the cost) -- use "pro" for the one hero shot
    per video, "schnell" for the rest. Both render the same STYLE_PREFIX.
    """
    if not FAL_API_KEY:
        raise IllustrationError("FAL_KEY is not set. Add it to .env (see .env.example).")

    endpoint = FAL_ENDPOINTS.get(model)
    if not endpoint:
        raise IllustrationError(f"Unknown fal.ai model {model!r}. Expected 'schnell' or 'pro'.")

    full_prompt = f"{STYLE_PREFIX} Scene: {scene_prompt}"

    payload = {"prompt": full_prompt, "image_size": image_size, "num_images": 1}
    if model == "schnell":
        payload["num_inference_steps"] = 4  # not a valid param for the pro endpoint

    try:
        resp = requests.post(
            endpoint,
            headers={"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as err:
        raise IllustrationError(f"fal.ai request failed: {err}") from err

    images = data.get("images") or []
    if not images or not images[0].get("url"):
        raise IllustrationError(f"fal.ai returned no image for prompt: {scene_prompt!r}")

    image_url = images[0]["url"]

    try:
        img_resp = requests.get(image_url, timeout=30)
        img_resp.raise_for_status()
    except requests.RequestException as err:
        raise IllustrationError(f"Could not download generated image: {err}") from err

    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(image_url.split("?")[0]).suffix or ".jpg"
    out_path = out_dir / f"{uuid.uuid4()}{suffix}"
    out_path.write_bytes(img_resp.content)
    return out_path


if __name__ == "__main__":
    # Quick smoke test.
    demo_dir = Path(__file__).resolve().parent / "temp"
    path = generate_illustration(
        "a half-built alien city set with a costumed actor standing beside unfinished scaffolding",
        demo_dir,
    )
    print(f"Wrote {path}")
