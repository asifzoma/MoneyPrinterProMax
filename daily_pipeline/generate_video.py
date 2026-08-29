"""Generate today's "Almost Movie" video via Remotion.

Orchestrates: almost_movies_topics (unmade film or film conspiracy theory +
Wikipedia grounding) -> Claude script/metadata/hashtags (Backend/gpt.py,
called directly, via the Anthropic API) -> ElevenLabs TTS narration
(elevenlabs_tts.py) -> AI-generated concept-art illustrations
(illustration_gen.py, via fal.ai) -> Remotion render
(daily_pipeline/remotion/) -> output/ + tracker.csv.

Script/metadata generation used to run on a local Ollama model, and
narration used to run through Backend/tiktokvoice.py's TikTok TTS proxy.
Both were swapped out after real reliability problems: Ollama timed out
under host memory pressure (CPU-only inference on a resource-constrained
machine), and the TikTok TTS proxy (ottsy.weilbyte.dev) had an outright
outage. Backend/gpt.py's swap to Anthropic lives in that shared module (it
also affects the older Flask app); elevenlabs_tts.py is its own new module
instead of editing Backend/tiktokvoice.py, since that module is shared with
the older app and this swap is scoped to daily_pipeline.

Formerly the "hidden histories of objects" pipeline (fetch_topic.py +
Wikimedia Commons real-photo search via Backend/commons_search.py and
Backend/video.py's download_image()) -- that concept is retired. Those
modules are left in place (fetch_topic.py, commons_search.py) but are no
longer imported here.

No Flask, no job queue, no Docker -- that machinery exists to support
MoneyPrinterProMax's multi-user web UI, which this single-video-a-day
pipeline doesn't need. Backend/gpt.py is Flask-independent, so we import
it directly.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import tracker
from almost_movies_topics import get_almost_movie
from elevenlabs_tts import tts
from illustration_gen import IllustrationError, generate_illustration
from srt_export import write_srt
from config import (
    BACKEND_DIR,
    DISCLAIMER,
    OUTPUT_DIR,
    PIPELINE_DIR,
    REMOTION_DIR,
    REMOTION_FPS,
    REMOTION_TMP_DIR,
)

sys.path.insert(0, str(BACKEND_DIR))
from gpt import generate_hashtags, generate_metadata, generate_script  # noqa: E402


def _find_binary(name: str, glob_patterns: list[str]) -> str:
    found = shutil.which(name)
    if found:
        return found
    for pattern in glob_patterns:
        matches = glob.glob(os.path.expandvars(pattern))
        if matches:
            return matches[0]
    raise RuntimeError(f"`{name}` not found on PATH or in known install locations.")


def _ffmpeg() -> str:
    return _find_binary(
        "ffmpeg",
        [r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*\bin\ffmpeg.exe"],
    )


def _ffprobe() -> str:
    return _find_binary(
        "ffprobe",
        [r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*\bin\ffprobe.exe"],
    )


def _remotion_cli() -> str:
    ext = ".cmd" if sys.platform == "win32" else ""
    cli = REMOTION_DIR / "node_modules" / ".bin" / f"remotion{ext}"
    if not cli.exists():
        raise RuntimeError(
            f"Remotion CLI not found at {cli}. Run `npm install` in {REMOTION_DIR} first."
        )
    return str(cli)


def _audio_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [_ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _concat_audio(mp3_paths: list[Path], output_path: Path) -> None:
    list_file = output_path.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in mp3_paths), encoding="utf-8"
    )
    subprocess.run(
        [_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    list_file.unlink(missing_ok=True)


def generate_daily_video(
    ai_model: str = None,
    voice: str = "en_us_001",
    min_duration: int = 60,
    max_images: int = 7,  # 1 poster-style hero shot (Flux Pro) + 6 scene shots (Flux Schnell)
) -> dict:
    ai_model = ai_model or os.environ.get("MP_OLLAMA_MODEL", "llama3.1:8b")

    print("[1/6] Picking today's entry...")
    topic, meta = get_almost_movie()
    print(f"  - {meta['film']} [{meta['type']}] ({meta['wikipedia_url']})")

    print("\n[2/6] Generating script...")
    # Same min-duration word-count-targeting approach MoneyPrinterProMax's
    # pipeline.py used: TikTok TTS speaks ~2.4 words/sec.
    words_per_second = 2.4
    accept_words = int(min_duration * words_per_second)
    target_words = int(accept_words * 1.2)
    max_words = int(accept_words * 1.6)
    script = None
    for attempt in range(1, 4):
        script = generate_script(topic, 6, ai_model, voice, "", min_words=target_words)
        word_count = len((script or "").split())
        if script and word_count >= accept_words:
            print(f"  script is {word_count} words (~{round(word_count / words_per_second)}s)")
            break
        print(f"  script was {word_count} words; need ~{accept_words}, retrying ({attempt}/3)...")
        target_words = int(target_words * 1.5)

    if not script:
        raise RuntimeError("Could not generate a script. Try a different model.")

    if len(script.split()) > max_words:
        kept, used = [], 0
        for sentence in re.split(r"(?<=[.!?])\s+", script.strip()):
            words_in = len(sentence.split())
            if used + words_in > max_words and kept:
                break
            kept.append(sentence)
            used += words_in
        script = " ".join(kept)

    print("\n[3/6] Generating concept-art illustrations...")
    REMOTION_TMP_DIR.mkdir(parents=True, exist_ok=True)
    for old in REMOTION_TMP_DIR.glob("*"):
        old.unlink()

    image_rel_paths = []
    try:
        hero_path = generate_illustration(meta["hero_prompt"], REMOTION_TMP_DIR, model="pro")
        image_rel_paths.append(f"tmp/{hero_path.name}")
    except IllustrationError as err:
        print(f"  [!] could not generate hero shot, opening with a scene shot instead: {err}")

    for scene_prompt in meta["scene_prompts"][: max_images - 1]:
        try:
            local_path = generate_illustration(scene_prompt, REMOTION_TMP_DIR)
            image_rel_paths.append(f"tmp/{local_path.name}")
        except IllustrationError as err:
            print(f"  [!] could not generate illustration: {err}")

    if not image_rel_paths:
        raise RuntimeError("Could not generate any illustrations.")
    print(f"  {len(image_rel_paths)} illustration(s) ready")

    print("\n[4/6] Generating narration (ElevenLabs)...")
    sentences = [s for s in script.split(". ") if s]
    tts_tmp_dir = PIPELINE_DIR / "temp"
    tts_tmp_dir.mkdir(parents=True, exist_ok=True)
    for old in tts_tmp_dir.glob("*.mp3"):
        old.unlink()

    sentence_paths = []
    for i, sentence in enumerate(sentences):
        path = tts_tmp_dir / f"sentence_{i}.mp3"
        tts(sentence, voice, filename=str(path))
        sentence_paths.append(path)

    captions = []
    cursor_seconds = 0.0
    for sentence, path in zip(sentences, sentence_paths):
        duration = _audio_duration_seconds(path)
        start_frame = round(cursor_seconds * REMOTION_FPS)
        cursor_seconds += duration
        end_frame = round(cursor_seconds * REMOTION_FPS)
        captions.append({"text": sentence.strip(), "startFrame": start_frame, "endFrame": end_frame})

    narration_path = REMOTION_TMP_DIR / "narration.mp3"
    _concat_audio(sentence_paths, narration_path)
    print(f"  narration is {cursor_seconds:.1f}s across {len(captions)} caption(s)")

    print("\n[5/6] Generating metadata...")
    title, description, keywords = generate_metadata(topic, script, ai_model)
    hashtags = generate_hashtags(topic, script, ai_model)
    description_with_disclaimer = description + DISCLAIMER

    print("\n[6/6] Rendering with Remotion...")
    props = {
        "title": title,
        "imagePaths": image_rel_paths,
        "audioPath": "tmp/narration.mp3",
        "captions": captions,
    }
    props_path = REMOTION_TMP_DIR / "props.json"
    props_path.write_text(json.dumps(props), encoding="utf-8")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60]
    saved_name = f"{slug or 'video'}-{uuid.uuid4().hex[:8]}.mp4"
    saved_path = OUTPUT_DIR / saved_name

    subprocess.run(
        [
            _remotion_cli(),
            "render",
            "src/index.ts",
            "HiddenHistory",
            str(saved_path),
            f"--props={props_path}",
        ],
        cwd=str(REMOTION_DIR),
        check=True,
    )
    print(f"  saved to output/{saved_name}")

    srt_sentences = [
        (c["text"], c["startFrame"] / REMOTION_FPS, c["endFrame"] / REMOTION_FPS)
        for c in captions
    ]
    srt_path = write_srt(srt_sentences, saved_path.with_suffix(".srt"))
    print(f"  captions saved to {srt_path.name}")

    hashtags_line = " ".join(hashtags)
    sidecar_text = (
        f"TITLE\n{title}\n\n"
        f"DESCRIPTION\n{description_with_disclaimer}\n\n"
        f"HASHTAGS\n{hashtags_line}\n\n"
        f"KEYWORDS / TAGS\n{', '.join(keywords)}\n"
    )
    sidecar_name = saved_name.rsplit(".", 1)[0] + ".txt"
    (OUTPUT_DIR / sidecar_name).write_text(sidecar_text, encoding="utf-8")

    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    tracker.append_row(
        date=today,
        video_filename=saved_name,
        title=title,
        description=description_with_disclaimer,
        hashtags=hashtags_line,
        youtube_url="",
        status="Pending",
    )
    print(f"  tracker row appended for {saved_name}")

    return {
        "video_path": str(saved_path),
        "txt_path": str(OUTPUT_DIR / sidecar_name),
        "title": title,
        "description": description_with_disclaimer,
        "hashtags": hashtags_line,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate today's Almost Movie video.")
    parser.add_argument("--model", default=None, help="Ollama model (default: $MP_OLLAMA_MODEL or llama3.1:8b)")
    parser.add_argument("--voice", default="en_us_001")
    parser.add_argument("--min-duration", type=int, default=60)
    args = parser.parse_args()

    try:
        result = generate_daily_video(ai_model=args.model, voice=args.voice, min_duration=args.min_duration)
    except Exception as err:
        print(f"\n[FAILED] {err}", file=sys.stderr)
        sys.exit(1)

    print(f"\nVideo: {result['video_path']}")
    print(f"Title: {result['title']}")
