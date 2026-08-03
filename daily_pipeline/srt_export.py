"""Write a .srt subtitle file from the same per-sentence timing data used to
drive the on-screen Remotion captions.

You already compute, for each sentence, a start and end time (originally to
sync the animated caption pop-ins to the narration -- see tiktokvoice.py /
the Remotion JSON builder). This just reuses that same list to also emit a
standard .srt file, which upload_youtube.py will pick up automatically
(it looks for <video_name>.srt next to the .mp4).

Usage from your generation code, once you have the per-sentence timings:

    from srt_export import write_srt

    # sentences: list of (text, start_seconds, end_seconds), in order
    write_srt(sentences, video_path.with_suffix(".srt"))

If your timing data is in frames (Remotion works in frames), convert first:
    start_seconds = start_frame / fps
    end_seconds = end_frame / fps
"""

from pathlib import Path
from typing import Iterable, Tuple


def _format_timestamp(seconds: float) -> str:
    """SRT timestamp format: HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:  # rounding edge case
        millis = 0
        secs += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(sentences: Iterable[Tuple[str, float, float]], out_path: Path) -> Path:
    """sentences: iterable of (text, start_seconds, end_seconds), in order.

    Writes a standard SRT file to out_path and returns it. Blank/whitespace-
    only sentences are skipped. Consecutive identical timestamps (shouldn't
    happen, but a zero-duration sentence would) get bumped by 0.3s so YouTube
    doesn't reject the block.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    blocks = []
    index = 1
    for text, start, end in sentences:
        text = (text or "").strip()
        if not text:
            continue
        if end <= start:
            end = start + 0.3
        blocks.append(
            f"{index}\n{_format_timestamp(start)} --> {_format_timestamp(end)}\n{text}\n"
        )
        index += 1

    out_path.write_text("\n".join(blocks), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    # Quick smoke test.
    demo = [
        ("The zipper was invented long before anyone trusted it.", 0.0, 3.2),
        ("It took over forty years to become a household fastener.", 3.2, 7.0),
    ]
    path = write_srt(demo, Path("demo.srt"))
    print(f"Wrote {path}")
    print(path.read_text())
