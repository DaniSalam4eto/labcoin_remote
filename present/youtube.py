"""Thin wrapper around ``yt-dlp`` for search + audio download.

We keep all yt-dlp specifics here so the rest of the package can stay
unaware of the library. Imports are lazy so the package can still be
introspected (``--help`` etc.) when yt-dlp is not installed yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class YouTubeError(RuntimeError):
    """Raised when search or download fails."""


@dataclass(frozen=True)
class VideoHit:
    id: str
    url: str
    title: str
    uploader: str | None
    duration: float | None


def _import_yt_dlp():
    try:
        import yt_dlp  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - install error path
        raise YouTubeError(
            "yt-dlp is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    return yt_dlp


def _common_opts() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "extract_flat": False,
        "skip_download": True,
        "socket_timeout": 45,
    }


def fetch_info(url: str) -> VideoHit | None:
    """Return metadata for ``url`` without downloading the audio."""

    yt_dlp = _import_yt_dlp()
    opts = _common_opts()
    with yt_dlp.YoutubeDL(opts) as ydl:
        entry = ydl.extract_info(url, download=False)
    if not entry or not entry.get("id"):
        return None
    return VideoHit(
        id=str(entry["id"]),
        url=entry.get("webpage_url") or url,
        title=str(entry.get("title") or ""),
        uploader=entry.get("uploader") or entry.get("channel"),
        duration=entry.get("duration"),
    )


def search(artist: str, title: str) -> VideoHit | None:
    """Return the top YouTube hit for ``artist - title`` or ``None``."""

    yt_dlp = _import_yt_dlp()
    query = f"ytsearch1:{artist} {title} audio"
    opts = _common_opts()
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
    if not info:
        return None
    entries = info.get("entries") or []
    if not entries:
        return None
    entry = entries[0]
    if not entry or not entry.get("id"):
        return None
    return VideoHit(
        id=str(entry["id"]),
        url=entry.get("webpage_url") or f"https://www.youtube.com/watch?v={entry['id']}",
        title=str(entry.get("title") or ""),
        uploader=entry.get("uploader") or entry.get("channel"),
        duration=entry.get("duration"),
    )


def download_audio(url: str, target_dir: Path) -> Path:
    """Download bestaudio for ``url`` into ``target_dir`` as a single M4A.

    Returns the path to the resulting file. Caller is responsible for
    cleaning up the temporary directory.
    """

    yt_dlp = _import_yt_dlp()
    target_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(target_dir / "%(id)s.%(ext)s")
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ],
        "prefer_ffmpeg": True,
        "overwrites": True,
        "geo_bypass": True,
        "socket_timeout": 90,
        "retries": 3,
        "fragment_retries": 3,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if not info:
        raise YouTubeError(f"yt-dlp returned no info for {url}")

    video_id = info.get("id")
    if not video_id:
        raise YouTubeError(f"yt-dlp produced no id for {url}")

    candidate = target_dir / f"{video_id}.m4a"
    if candidate.exists():
        return candidate

    # Postprocessor sometimes emits a different extension; pick the
    # newest matching file as a fallback.
    matches = sorted(
        target_dir.glob(f"{video_id}.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in matches:
        if path.suffix.lower() in {".m4a", ".mp4", ".aac", ".mp3", ".opus", ".webm"}:
            return path
    raise YouTubeError(f"download succeeded but no audio file found for {url}")
