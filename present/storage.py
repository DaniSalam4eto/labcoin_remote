"""Filesystem-backed storage for the song library.

Layout::

    data/
      index.json
      songs/<song_id>/
        metadata.json
        clip_1.m4a
        clip_2.m4a
        clip_3.m4a
        clip_4.m4a

`index.json` keeps a lightweight summary of every song so the CLI and
web service can list the library without touching every per-song file.
Per-song `metadata.json` holds the full record (chart source, YouTube
ID, clip positions, etc.).
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from bundle_paths import app_base_dir

PROJECT_ROOT = app_base_dir()
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
INDEX_VERSION = 1

# Latin → ASCII fallback for filesystem-friendly IDs. We accept arbitrary
# unicode in artist/title strings but the on-disk folder name is sanitized.
_SAFE_RE = re.compile(r"[^\w\-]+", re.UNICODE)
_UNDERSCORES_RE = re.compile(r"_+")

_INDEX_FIELDS = (
    "id",
    "artist",
    "title",
    "origin",
    "added_at",
    "duration",
    "youtube_id",
    "youtube_title",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_name(value: str) -> str:
    """Return a filesystem-safe representation of `value`.

    Keeps letters/digits/underscore/hyphen, collapses runs of separators
    to a single underscore, trims edges. Falls back to ``"untitled"``
    when the input has no usable characters.
    """

    cleaned = _SAFE_RE.sub("_", value.strip())
    cleaned = _UNDERSCORES_RE.sub("_", cleaned).strip("_-")
    return cleaned or "untitled"


def make_song_id(artist: str, title: str) -> str:
    """Stable id used as the folder name and dictionary key."""

    return f"{safe_name(artist)}_-_{safe_name(title)}"


@dataclass(frozen=True)
class SongRecord:
    id: str
    artist: str
    title: str
    origin: str  # "bg" | "global"
    added_at: str
    duration: float | None = None
    youtube_id: str | None = None
    youtube_title: str | None = None
    youtube_url: str | None = None
    chart_source: str | None = None
    clip_positions: tuple[float, ...] | None = None
    clips: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "artist": self.artist,
            "title": self.title,
            "origin": self.origin,
            "added_at": self.added_at,
            "duration": self.duration,
            "youtube_id": self.youtube_id,
            "youtube_title": self.youtube_title,
            "youtube_url": self.youtube_url,
            "chart_source": self.chart_source,
            "clip_positions": (
                list(self.clip_positions) if self.clip_positions else None
            ),
            "clips": list(self.clips),
        }
        return data


class Storage:
    """Thin wrapper around the on-disk layout under ``data/``."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.songs_dir = self.data_dir / "songs"
        self.index_path = self.data_dir / "index.json"
        self._index_lock = threading.Lock()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.songs_dir.mkdir(exist_ok=True)

    # ----- index -----------------------------------------------------

    def load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"version": INDEX_VERSION, "updated_at": None, "songs": []}
        with self.index_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        # tolerate legacy / hand-edited files
        data.setdefault("version", INDEX_VERSION)
        data.setdefault("songs", [])
        return data

    def save_index(self, index: dict[str, Any]) -> None:
        index["version"] = INDEX_VERSION
        index["updated_at"] = _now_iso()
        index["songs"].sort(
            key=lambda s: (s.get("origin", ""), s.get("artist", ""), s.get("title", ""))
        )
        tmp = self.index_path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(index, handle, ensure_ascii=False, indent=2)
        tmp.replace(self.index_path)

    # ----- per-song --------------------------------------------------

    def song_dir(self, song_id: str) -> Path:
        return self.songs_dir / song_id

    def has(self, song_id: str) -> bool:
        meta = self.song_dir(song_id) / "metadata.json"
        if not meta.exists():
            return False
        # Treat a folder with no clips as incomplete so the pipeline retries.
        clips = sorted(self.song_dir(song_id).glob("clip_*.m4a"))
        return len(clips) >= 1

    def read_metadata(self, song_id: str) -> dict[str, Any] | None:
        meta = self.song_dir(song_id) / "metadata.json"
        if not meta.exists():
            return None
        with meta.open(encoding="utf-8") as handle:
            return json.load(handle)

    def write_metadata(self, song_id: str, payload: dict[str, Any]) -> Path:
        sd = self.song_dir(song_id)
        sd.mkdir(parents=True, exist_ok=True)
        path = sd / "metadata.json"
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        tmp.replace(path)
        return path

    def upsert(self, record: SongRecord) -> None:
        self.write_metadata(record.id, record.to_dict())
        with self._index_lock:
            index = self.load_index()
            index["songs"] = [s for s in index["songs"] if s.get("id") != record.id]
            full = record.to_dict()
            index["songs"].append({k: full.get(k) for k in _INDEX_FIELDS})
            self.save_index(index)

    def remove(self, song_id: str) -> bool:
        sd = self.song_dir(song_id)
        existed = sd.exists()
        if existed:
            shutil.rmtree(sd, ignore_errors=True)
        with self._index_lock:
            index = self.load_index()
            before = len(index["songs"])
            index["songs"] = [s for s in index["songs"] if s.get("id") != song_id]
            if before != len(index["songs"]) or existed:
                self.save_index(index)
                return True
            return False

    # ----- queries ---------------------------------------------------

    def list_songs(self) -> list[dict[str, Any]]:
        return list(self.load_index().get("songs", []))

    def iter_records(self) -> Iterable[dict[str, Any]]:
        for entry in self.list_songs():
            full = self.read_metadata(entry["id"])
            if full:
                yield full

    def clip_path(self, song_id: str, clip_index: int) -> Path | None:
        if clip_index < 1:
            return None
        candidate = self.song_dir(song_id) / f"clip_{clip_index}.m4a"
        return candidate if candidate.exists() else None

    def rebuild_index_from_disk(self) -> int:
        """Re-derive ``index.json`` from on-disk per-song metadata.

        Useful after manual edits or restoring from backup. Returns the
        number of songs in the rebuilt index.
        """

        songs: list[dict[str, Any]] = []
        for sd in sorted(self.songs_dir.iterdir()):
            if not sd.is_dir():
                continue
            meta = sd / "metadata.json"
            if not meta.exists():
                continue
            with meta.open(encoding="utf-8") as handle:
                data = json.load(handle)
            songs.append({k: data.get(k) for k in _INDEX_FIELDS})
        with self._index_lock:
            self.save_index({"version": INDEX_VERSION, "songs": songs})
        return len(songs)
