"""Generate moody, cinematic concept-art illustrations via fal.ai's Flux
Schnell model -- standing in for the object-history pipeline's real-photo
Wikimedia Commons search (commons_search.py) now that every scene needs to
depict something that was never actually filmed.

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

FAL_ENDPOINT = "https://fal.run/fal-ai/flux/schnell"

STYLE_PREFIX = (
    "Moody cinematic concept art, dramatic chiaroscuro lighting, a "
    "desaturated color grade with one accent color, painterly digital "
    "matte-painting brushwork, subtle 35mm film grain, widescreen framing, "
    "an unfinished never-released production feel -- like a lost pitch-deck "
    "painting for a movie that never got made. Atmospheric and evocative, "
    "not literal. This is an original artistic interpretation only: do not "
    "depict any specific real actor's likeness, any real leaked costume "
    "photo, or any real production still -- invent the imagery from the "
    "scene description alone."
)


class IllustrationError(Exception):
    """Raised when fal.ai fails to return a usable image."""


def generate_illustration(scene_prompt: str, out_dir: Path, image_size: str = "portrait_16_9") -> Path:
    """Generate one concept-art illustration for `scene_prompt` and save it
    under `out_dir`. Returns the local path.

    `scene_prompt` should describe one moment from the almost-made film
    (e.g. "a costumed actor standing on a half-built alien city set") --
    not the STYLE_PREFIX, which is prepended here automatically.
    """
    if not FAL_API_KEY:
        raise IllustrationError("FAL_KEY is not set. Add it to .env (see .env.example).")

    full_prompt = f"{STYLE_PREFIX} Scene: {scene_prompt}"

    try:
        resp = requests.post(
            FAL_ENDPOINT,
            headers={"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"},
            json={
                "prompt": full_prompt,
                "image_size": image_size,
                "num_images": 1,
                "num_inference_steps": 4,
            },
            timeout=60,
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
