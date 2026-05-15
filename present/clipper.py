"""ffmpeg-driven clip cutter.

Produces four 15-second M4A clips per song from positions evenly spaced
across the middle of the track. ``ffmpeg`` and ``ffprobe`` must be on
``PATH`` — see the README for install steps.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

CLIP_COUNT = 4
CLIP_LEN = 15.0  # seconds
SKIP_HEAD = 15.0
SKIP_TAIL = 15.0


class ClipperError(RuntimeError):
    """ffmpeg/ffprobe failure or audio too short."""


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ClipperError(
            f"`{name}` not found on PATH. Install ffmpeg and ensure both "
            "`ffmpeg` and `ffprobe` are reachable."
        )
    return path


def probe_duration(audio_path: Path) -> float:
    """Return audio duration in seconds (via ffprobe -show_format)."""

    ffprobe = _require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ClipperError(
            f"ffprobe failed for {audio_path.name}: {result.stderr.strip()}"
        )
    try:
        parsed = json.loads(result.stdout or "{}")
        return float(parsed["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ClipperError(
            f"ffprobe returned no usable duration for {audio_path.name}"
        ) from exc


def compute_positions(
    duration: float,
    count: int = CLIP_COUNT,
    clip_len: float = CLIP_LEN,
    skip_head: float = SKIP_HEAD,
    skip_tail: float = SKIP_TAIL,
    randomize: bool = True,
    rng: random.Random | None = None,
) -> list[float]:
    """Return ``count`` non-overlapping start offsets across the middle.

    Each clip is ``clip_len`` seconds long and the windows skip the
    leading ``skip_head`` / trailing ``skip_tail`` seconds. When
    ``randomize`` is true (default) the offsets are picked at random
    inside ``count`` equal-sized buckets so no two windows can collide.
    """

    if duration <= 0:
        raise ClipperError("duration must be positive")

    head = skip_head
    tail = skip_tail
    usable = duration - head - tail

    if usable < clip_len:
        head = max(1.0, min(skip_head, duration * 0.1))
        tail = max(1.0, min(skip_tail, duration * 0.1))
        usable = duration - head - tail
    if usable < clip_len:
        raise ClipperError(
            f"audio is too short ({duration:.1f}s) to produce {count} "
            f"{clip_len:.0f}s clips"
        )

    if not randomize:
        slack = usable - clip_len
        return [head + (i + 1) * slack / (count + 1) for i in range(count)]

    bucket = usable / count
    if bucket < clip_len:
        slack = usable - clip_len
        if slack <= 0 or count <= 1:
            return [head] * count
        return [head + (i + 1) * slack / (count + 1) for i in range(count)]

    r = rng or random.Random()
    starts: list[float] = []
    for i in range(count):
        slot_start = head + i * bucket
        slot_room = bucket - clip_len
        offset = r.uniform(0.0, slot_room) if slot_room > 0 else 0.0
        starts.append(slot_start + offset)
    return starts


def cut_clip(
    audio_path: Path,
    output_path: Path,
    start: float,
    duration: float = CLIP_LEN,
) -> None:
    """Cut a single ``duration`` window from ``audio_path`` to ``output_path``."""

    ffmpeg = _require_binary("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(audio_path),
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not output_path.exists():
        raise ClipperError(
            f"ffmpeg failed cutting clip @ {start:.2f}s: {result.stderr.strip()}"
        )


def make_clips(audio_path: Path, output_dir: Path) -> tuple[list[Path], list[float], float]:
    """Cut four clips and return ``(paths, positions, duration)``."""

    duration = probe_duration(audio_path)
    positions = compute_positions(duration)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for index, start in enumerate(positions, start=1):
        target = output_dir / f"clip_{index}.m4a"
        cut_clip(audio_path, target, start=start)
        paths.append(target)
    return paths, positions, duration
