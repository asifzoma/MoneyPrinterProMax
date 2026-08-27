"""Text-to-speech via the ElevenLabs API.

Replaces Backend/tiktokvoice.py's TikTok TTS proxy (ottsy.weilbyte.dev),
which had a real, unrelated outage that blocked generate_video.py's
narration step. Kept as its own module rather than editing
Backend/tiktokvoice.py -- that module is shared with the older
MoneyPrinterProMax Flask app, and this swap is scoped to daily_pipeline.

Requires ELEVENLABS_API_KEY in .env. Get one at
https://elevenlabs.io/app/settings/api-keys.
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from config import REPO_ROOT

load_dotenv(REPO_ROOT / ".env")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
# "George" -- a premade voice on this account's own default roster (unlike
# "Rachel", a Voice Library voice that returned 402 "Free users cannot use
# library voices via the API" on this plan). Confirmed via GET /v1/voices.
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

ELEVENLABS_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


class TTSError(Exception):
    """Raised when ElevenLabs fails to return usable audio."""


def tts(text: str, voice: str = None, filename: str = "output.mp3") -> None:
    """Generate narration audio for `text` and write it to `filename`.

    `voice` is accepted for call-site compatibility with the TikTok TTS
    tts() function this replaces (generate_video.py still passes its old
    TikTok voice ID, e.g. "en_us_001") but is unused -- ElevenLabs voice
    selection is controlled via ELEVENLABS_VOICE_ID instead.
    """
    if not ELEVENLABS_API_KEY:
        raise TTSError("ELEVENLABS_API_KEY is not set. Add it to .env.")

    if not text:
        raise TTSError("No text given for TTS.")

    try:
        resp = requests.post(
            ELEVENLABS_ENDPOINT.format(voice_id=ELEVENLABS_VOICE_ID),
            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json={"text": text, "model_id": ELEVENLABS_MODEL_ID},
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as err:
        raise TTSError(f"ElevenLabs request failed: {err}") from err

    if not resp.content:
        raise TTSError("ElevenLabs returned no audio data.")

    Path(filename).write_bytes(resp.content)


if __name__ == "__main__":
    demo_path = Path(__file__).resolve().parent / "temp" / "elevenlabs_demo.mp3"
    demo_path.parent.mkdir(parents=True, exist_ok=True)
    tts("This is a quick test of the ElevenLabs text to speech swap.", filename=str(demo_path))
    print(f"Wrote {demo_path}")
