"""High-level operations: build / refresh the library, add or remove songs.

Each entry point accepts an optional ``log`` callback so the CLI can
stream progress to stdout and the web service can capture per-job logs
without changes here.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import charts, clipper, youtube
from .storage import SongRecord, Storage, make_song_id

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int], None]


def _noop_log(_msg: str) -> None:
    pass


def _noop_progress(_current: int, _total: int) -> None:
    pass


@dataclass
class RunResult:
    success: int
    skipped: int
    failed: int
    failures: list[tuple[str, str]]  # (song_id, reason)

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "skipped": self.skipped,
            "failed": self.failed,
            "failures": [{"id": sid, "reason": reason} for sid, reason in self.failures],
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def process_song(
    artist: str,
    title: str,
    origin: str,
    storage: Storage,
    log: LogFn = _noop_log,
    chart_source: str | None = None,
) -> SongRecord:
    """Download + clip a single song and write its metadata."""

    song_id = make_song_id(artist, title)
    log(f"-> {song_id} ({origin})")

    hit = youtube.search(artist, title)
    if not hit:
        raise youtube.YouTubeError("no YouTube result")
    log(f"   youtube: {hit.id} ({hit.duration or '?'}s) {hit.title!r}")

    tmp_root = Path(tempfile.mkdtemp(prefix="present_dl_"))
    try:
        audio_path = youtube.download_audio(hit.url, tmp_root)
        log(f"   downloaded {audio_path.name}")

        song_dir = storage.song_dir(song_id)
        if song_dir.exists():
            # Clear out any half-finished previous attempt so we don't
            # leave orphan clips alongside the new set.
            for p in song_dir.glob("clip_*.m4a"):
                p.unlink(missing_ok=True)
        song_dir.mkdir(parents=True, exist_ok=True)

        clip_paths, positions, duration = clipper.make_clips(audio_path, song_dir)
        log(f"   clipped @ {[round(p, 1) for p in positions]} from {duration:.1f}s")

        record = SongRecord(
            id=song_id,
            artist=artist,
            title=title,
            origin=origin,
            added_at=_now_iso(),
            duration=duration,
            youtube_id=hit.id,
            youtube_title=hit.title,
            youtube_url=hit.url,
            chart_source=chart_source,
            clip_positions=tuple(positions),
            clips=tuple(p.name for p in clip_paths),
        )
        storage.upsert(record)
        return record
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def process_song_from_url(
    artist: str,
    title: str,
    origin: str,
    url: str,
    storage: Storage,
    log: LogFn = _noop_log,
    chart_source: str | None = "manual-url",
) -> SongRecord:
    """Download + clip a song from an explicit YouTube URL."""

    song_id = make_song_id(artist, title)
    log(f"-> {song_id} ({origin}) from {url}")

    log("   fetching video info…")
    hit = youtube.fetch_info(url)
    if not hit:
        raise youtube.YouTubeError(f"could not read metadata for {url}")
    log(f"   youtube: {hit.id} ({hit.duration or '?'}s) {hit.title!r}")

    tmp_root = Path(tempfile.mkdtemp(prefix="present_dl_"))
    try:
        log("   downloading audio with yt-dlp (may take several minutes)…")
        audio_path = youtube.download_audio(hit.url, tmp_root)
        log(f"   downloaded {audio_path.name}")

        song_dir = storage.song_dir(song_id)
        if song_dir.exists():
            for p in song_dir.glob("clip_*.m4a"):
                p.unlink(missing_ok=True)
        song_dir.mkdir(parents=True, exist_ok=True)

        clip_paths, positions, duration = clipper.make_clips(audio_path, song_dir)
        log(f"   clipped @ {[round(p, 1) for p in positions]} from {duration:.1f}s")

        record = SongRecord(
            id=song_id,
            artist=artist,
            title=title,
            origin=origin,
            added_at=_now_iso(),
            duration=duration,
            youtube_id=hit.id,
            youtube_title=hit.title,
            youtube_url=hit.url,
            chart_source=chart_source,
            clip_positions=tuple(positions),
            clips=tuple(p.name for p in clip_paths),
        )
        storage.upsert(record)
        return record
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def add_song_from_url(
    artist: str,
    title: str,
    url: str,
    origin: str = "global",
    storage: Storage | None = None,
    log: LogFn = _noop_log,
    overwrite: bool = False,
) -> SongRecord:
    """Insert a song into the library using an explicit YouTube URL."""

    storage = storage or Storage()
    if origin not in {"bg", "global"}:
        raise ValueError("origin must be 'bg' or 'global'")
    if not url or "://" not in url:
        raise ValueError("url must be a fully-qualified http(s) URL")
    song_id = make_song_id(artist, title)
    if storage.has(song_id) and not overwrite:
        log(f"   already present, skipping: {song_id}")
        existing = storage.read_metadata(song_id) or {}
        return SongRecord(
            id=song_id,
            artist=existing.get("artist", artist),
            title=existing.get("title", title),
            origin=existing.get("origin", origin),
            added_at=existing.get("added_at", _now_iso()),
            duration=existing.get("duration"),
            youtube_id=existing.get("youtube_id"),
            youtube_title=existing.get("youtube_title"),
            youtube_url=existing.get("youtube_url"),
            chart_source=existing.get("chart_source"),
        )
    return process_song_from_url(
        artist, title, origin, url, storage, log=log, chart_source="manual-url"
    )


def add_song(
    artist: str,
    title: str,
    origin: str = "global",
    storage: Storage | None = None,
    log: LogFn = _noop_log,
    overwrite: bool = False,
) -> SongRecord:
    """Insert a single song into the library."""

    storage = storage or Storage()
    if origin not in {"bg", "global"}:
        raise ValueError("origin must be 'bg' or 'global'")
    song_id = make_song_id(artist, title)
    if storage.has(song_id) and not overwrite:
        log(f"   already present, skipping: {song_id}")
        existing = storage.read_metadata(song_id) or {}
        return SongRecord(
            id=song_id,
            artist=existing.get("artist", artist),
            title=existing.get("title", title),
            origin=existing.get("origin", origin),
            added_at=existing.get("added_at", _now_iso()),
            duration=existing.get("duration"),
            youtube_id=existing.get("youtube_id"),
            youtube_title=existing.get("youtube_title"),
            youtube_url=existing.get("youtube_url"),
            chart_source=existing.get("chart_source"),
        )
    return process_song(artist, title, origin, storage, log=log, chart_source="manual")


def remove_song(
    song_id: str,
    storage: Storage | None = None,
    log: LogFn = _noop_log,
) -> bool:
    storage = storage or Storage()
    removed = storage.remove(song_id)
    log(f"removed: {song_id}" if removed else f"not in library: {song_id}")
    return removed


def initialize_library(
    target: int = 200,
    bg_ratio: float = 0.4,
    storage: Storage | None = None,
    log: LogFn = _noop_log,
    progress: ProgressFn = _noop_progress,
) -> RunResult:
    """Build the library from scratch (or top up to ``target`` songs)."""

    storage = storage or Storage()
    log(f"initialize_library: target={target} bg_ratio={bg_ratio}")
    candidates = charts.gather_candidates(target=target, bg_ratio=bg_ratio, log=log)
    log(f"candidates: {len(candidates)}")

    success = skipped = failed = 0
    failures: list[tuple[str, str]] = []
    total = len(candidates)

    for index, cand in enumerate(candidates, start=1):
        progress(index, total)
        artist = cand["artist"]
        title = cand["title"]
        origin = cand.get("origin", "global")
        source = cand.get("source")
        song_id = make_song_id(artist, title)
        if storage.has(song_id):
            skipped += 1
            log(f"[{index}/{total}] skip (exists): {song_id}")
            continue
        try:
            process_song(artist, title, origin, storage, log=log, chart_source=source)
            success += 1
        except Exception as exc:  # noqa: BLE001 — keep going on per-song errors
            failed += 1
            reason = f"{type(exc).__name__}: {exc}"
            failures.append((song_id, reason))
            log(f"[{index}/{total}] FAILED {song_id}: {reason}")

    progress(total, total)
    log(
        f"done: success={success} skipped={skipped} failed={failed} "
        f"(library now {len(storage.list_songs())})"
    )
    return RunResult(success=success, skipped=skipped, failed=failed, failures=failures)


def refresh_library(
    target: int = 200,
    bg_ratio: float = 0.4,
    storage: Storage | None = None,
    log: LogFn = _noop_log,
    progress: ProgressFn = _noop_progress,
) -> RunResult:
    """Retry failed/missing entries and top up toward ``target``.

    Identical to :func:`initialize_library` because the latter is already
    idempotent (it skips songs that have complete clips). The separate
    name exists for the CLI verb and to leave room for divergent logic
    (e.g. "force re-clip" mode) later.
    """

    return initialize_library(
        target=target,
        bg_ratio=bg_ratio,
        storage=storage,
        log=log,
        progress=progress,
    )
