"""Glue between the PRESENT clip library and the pygame mixer.

Provides two things the game flow in ``app.py`` needs:

* :func:`pick_random_song` — read ``data/index.json`` produced by the
  ``present`` package and return a random ``(SongPick)`` with the path to
  one of its four 15-second M4A clips.
* :class:`ClipPlayer` — play those clips through the pygame mixer.

Pygame's bundled SDL_mixer can play WAV/OGG/MP3 reliably but not AAC/M4A,
so :class:`ClipPlayer` transcodes each clip to a temporary WAV on first
use (via ``ffmpeg``) and reuses the WAV for subsequent plays.
"""

from __future__ import annotations

import math
import random
import shutil
import subprocess
import struct
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import pygame
except ImportError:  # pragma: no cover - desktop app dep is mandatory
    pygame = None  # type: ignore[assignment]

from present.storage import Storage


def _rms_s16le_mono(fragment: bytes) -> float:
    """RMS of signed 16-bit little-endian PCM (PEP 594 dropped ``audioop`` in 3.13)."""

    nbytes = (len(fragment) >> 1) << 1
    if nbytes < 2:
        return 0.0
    n_samples = nbytes // 2
    samp = struct.unpack(f"<{n_samples}h", fragment[:nbytes])
    if not samp:
        return 0.0
    tot = sum(float(v) * float(v) for v in samp)
    return math.sqrt(tot / n_samples)


def _stereo_s16le_to_mono_average(raw_stereo: bytes) -> bytes:
    """Stereo interleaved s16 LE → mono s16 LE (average L/R per frame)."""

    n_pairs = len(raw_stereo) // 4
    ob = bytearray(n_pairs * 2)
    for i in range(n_pairs):
        ls, rs = struct.unpack_from("<hh", raw_stereo, i * 4)
        mixed = max(-32768, min(32767, (ls + rs) // 2))
        struct.pack_into("<h", ob, i * 2, mixed)
    return bytes(ob)


CLIPS_PER_SONG = 4
HISTORY_LIMIT = 24  # avoid replaying the same song within this many picks


@dataclass(frozen=True)
class SongPick:
    """One pick from the library: song metadata + the chosen clip path."""

    song_id: str
    artist: str
    title: str
    origin: str
    clip_index: int   # 1..4
    clip_path: Path


class LibraryEmpty(RuntimeError):
    """Raised when no playable songs are available."""


def _candidate_clips(storage: Storage, song_id: str) -> list[tuple[int, Path]]:
    """Return ``(index, path)`` pairs for every clip that exists on disk."""

    out: list[tuple[int, Path]] = []
    for index in range(1, CLIPS_PER_SONG + 1):
        path = storage.clip_path(song_id, index)
        if path is not None:
            out.append((index, path))
    return out


def pick_random_song(
    storage: Storage | None = None,
    *,
    exclude_song_ids: Iterable[str] = (),
    rng: random.Random | None = None,
) -> SongPick:
    """Pick a random playable song from the library.

    Songs missing all of their clips are skipped automatically. Pass
    ``exclude_song_ids`` to avoid recent repeats; if that drains the
    pool the function ignores the filter and tries again.
    """

    storage = storage or Storage()
    songs = storage.list_songs()
    if not songs:
        raise LibraryEmpty("data/index.json is empty — run `python -m present init`")

    rng = rng or random.SystemRandom()
    exclude = set(exclude_song_ids)

    pool = [s for s in songs if s.get("id") not in exclude]
    if not pool:
        pool = list(songs)
    rng.shuffle(pool)

    for song in pool:
        song_id = song.get("id")
        if not song_id:
            continue
        clips = _candidate_clips(storage, song_id)
        if not clips:
            continue
        clip_index, clip_path = rng.choice(clips)
        return SongPick(
            song_id=song_id,
            artist=str(song.get("artist", "?")),
            title=str(song.get("title", "?")),
            origin=str(song.get("origin", "global")),
            clip_index=clip_index,
            clip_path=clip_path,
        )

    raise LibraryEmpty(
        "library has entries but no clip_*.m4a files exist on disk"
    )


def pick_same_song_other_clip(
    song_id: str,
    exclude_index: int,
    *,
    storage: Storage | None = None,
    rng: random.Random | None = None,
) -> tuple[int, Path]:
    """Return ``(clip_index, path)`` for a different clip of the same song.

    If only one clip exists (unusual), returns that same clip again.
    """

    storage = storage or Storage()
    rng = rng or random.SystemRandom()
    candidates = _candidate_clips(storage, song_id)
    if not candidates:
        raise LibraryEmpty(f"no clips for song {song_id!r}")
    others = [(i, p) for i, p in candidates if i != exclude_index]
    pick_from = others if others else candidates
    idx, path = rng.choice(pick_from)
    return idx, path


# ---------------------------------------------------------------- player


class ClipPlayer:
    """pygame.mixer wrapper that transcodes M4A → WAV on first use.

    Each decoded WAV is cached in a per-process temp directory; the same
    clip plays from the cache on subsequent rounds without re-running
    ``ffmpeg``. :meth:`close` deletes the temp directory.

    :meth:`get_visual_levels` derives bar heights from the **actual PCM**
    decoded from that WAV (mono RMS in small time slices), roughly synced by
    wall-clock elapsed time — not an arbitrary looping animation.
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        if pygame is None:  # pragma: no cover - import guarded above
            raise RuntimeError("pygame is required for ClipPlayer")
        self._sample_rate = sample_rate
        self._tmp: Path | None = None
        self._cache: dict[Path, Path] = {}
        self._wav_mono_cache: dict[Path, tuple[bytes, int]] = {}
        self._channel: "pygame.mixer.Channel | None" = None
        self._sound: "pygame.mixer.Sound | None" = None
        self._initialised = False
        self._ffmpeg = shutil.which("ffmpeg")
        self._viz_pcm: bytes | None = None
        self._viz_rate: int = 44100
        self._playback_start_mono: float = 0.0
        self._viz_smooth: list[float] | None = None
        self._viz_peak_follow: float = 1200.0
        self._manual_pause: bool = False
        # Clips always play at full volume (the on-screen volume manager was
        # removed). Kept as a constant so playback stays at 100%.
        self._current_length_s: float = 0.0

    # ---- setup ----------------------------------------------------------

    def ensure_mixer(self) -> bool:
        """Initialise ``pygame.mixer`` lazily. Returns False on failure."""

        if self._initialised:
            return True
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=self._sample_rate, size=-16, channels=2)
            self._initialised = True
            return True
        except pygame.error as exc:
            print(f"[audio] mixer init failed: {exc}", file=sys.stderr)
            return False

    def _temp_dir(self) -> Path:
        if self._tmp is None:
            self._tmp = Path(tempfile.mkdtemp(prefix="labcoin_clips_"))
        return self._tmp

    # ---- decoding -------------------------------------------------------

    def _decode_to_wav(self, m4a_path: Path) -> Path:
        if not self._ffmpeg:
            raise RuntimeError(
                "ffmpeg not on PATH — install ffmpeg to play clips."
            )
        wav_path = self._temp_dir() / f"{m4a_path.parent.name}__{m4a_path.stem}.wav"
        if wav_path.exists():
            return wav_path
        result = subprocess.run(
            [
                self._ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(m4a_path),
                "-ar",
                str(self._sample_rate),
                "-ac",
                "2",
                "-f",
                "wav",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not wav_path.exists():
            raise RuntimeError(
                f"ffmpeg decode failed for {m4a_path.name}: "
                f"{result.stderr.strip() or 'unknown error'}"
            )
        return wav_path

    def _playable_path(self, m4a_path: Path) -> Path:
        if m4a_path in self._cache:
            return self._cache[m4a_path]
        wav = self._decode_to_wav(m4a_path)
        self._cache[m4a_path] = wav
        return wav

    def _wav_to_mono_pcm(self, wav_path: Path) -> tuple[bytes, int]:
        cached = self._wav_mono_cache.get(wav_path)
        if cached is not None:
            return cached

        bad = (b"", max(1, self._sample_rate))
        try:
            with wave.open(str(wav_path), "rb") as wf:
                if wf.getcomptype() != "NONE":
                    self._wav_mono_cache[wav_path] = bad
                    return bad
                rate = wf.getframerate()
                sw = wf.getsampwidth()
                ch = wf.getnchannels()
                nf = wf.getnframes()
                raw = wf.readframes(max(0, nf))
        except (OSError, wave.Error, ValueError):
            self._wav_mono_cache[wav_path] = bad
            return bad

        if sw != 2:
            self._wav_mono_cache[wav_path] = bad
            return bad

        if ch == 2:
            mono_bytes = _stereo_s16le_to_mono_average(raw)
        elif ch == 1:
            mono_bytes = raw
        else:
            self._wav_mono_cache[wav_path] = bad
            return bad

        out = (mono_bytes, max(1, rate))
        self._wav_mono_cache[wav_path] = out
        return out

    # ---- playback -------------------------------------------------------

    def current_length_s(self) -> float:
        """Length of the clip loaded by the last :meth:`play` (seconds)."""

        return self._current_length_s

    def play(self, clip_path: Path) -> bool:
        """Stop any current clip and start ``clip_path`` at full volume.

        Returns ``True`` on success, ``False`` if the mixer is unusable
        or decoding failed (the caller can keep going silently).
        """

        if not self.ensure_mixer():
            return False
        try:
            self.stop()
            wav = self._playable_path(clip_path)
            pcm_mono, vz_rate = self._wav_to_mono_pcm(wav)
            sound = pygame.mixer.Sound(str(wav))
            sound.set_volume(1.0)
            self._sound = sound
            self._channel = sound.play()
            try:
                self._current_length_s = float(sound.get_length())
            except pygame.error:
                self._current_length_s = 0.0
            self._viz_pcm = pcm_mono if len(pcm_mono) > 64 else None
            self._viz_rate = vz_rate
            self._playback_start_mono = time.monotonic()
            self._viz_smooth = None
            self._viz_peak_follow = 1100.0
            self._manual_pause = False
            return self._channel is not None
        except Exception as exc:  # noqa: BLE001 — degrade quietly
            print(f"[audio] failed to play {clip_path.name}: {exc}", file=sys.stderr)
            return False

    def buzz_pause(self) -> None:
        """Pause playback mid-clip after a buzz (audio stops until host resolves)."""

        if self._channel is None:
            return
        try:
            if self._channel.get_busy():
                self._channel.pause()
                self._manual_pause = True
        except pygame.error:
            pass

    def undo_buzz_pause(self) -> None:
        """Continue the clip after host voids the buzz (`buzz_pause`)."""

        if self._channel is None:
            return
        try:
            self._channel.unpause()
        except pygame.error:
            pass
        self._manual_pause = False

    def buzz_paused(self) -> bool:
        return bool(self._manual_pause)

    def stop(self) -> None:
        if self._channel is not None and self._channel.get_busy():
            try:
                self._channel.stop()
            except pygame.error:
                pass
        self._channel = None
        self._sound = None
        self._viz_pcm = None
        self._manual_pause = False

    def is_playing(self) -> bool:
        return bool(self._channel and self._channel.get_busy())

    def get_visual_levels(self, bands: int) -> tuple[list[float], bool]:
        """Return ``bands`` heights in ``[0, 1]`` from RMS of decoded PCM.

        Second value is True when heights follow the waveform (mixer playing);
        otherwise the caller should draw its own idle motion.
        """

        if bands < 1:
            return [], False
        if self._manual_pause:
            return [0.06] * bands, False
        if not self._viz_pcm or not self.is_playing():
            return [0.06] * bands, False

        pcm = self._viz_pcm
        rate = self._viz_rate
        nbytes = len(pcm)
        nsamples = nbytes // 2
        if nsamples < 32:
            return [0.1] * bands, True

        elapsed = max(0.0, time.monotonic() - self._playback_start_mono)
        centre = min(nsamples - 1, max(0, int(elapsed * rate)))

        span = max(rate * 20 // 100, bands * 36)
        span = min(span, nsamples)
        half = span // 2
        lo = max(0, centre - half)
        hi = min(nsamples, lo + span)
        if hi - lo < bands * 12:
            lo = max(0, nsamples - span)
            hi = nsamples

        chunk_bytes = pcm[lo * 2 : hi * 2]
        nchk = len(chunk_bytes) // 2

        raw_rms: list[float] = []
        for i in range(bands):
            a = i * nchk // bands
            b = (i + 1) * nchk // bands
            frag = chunk_bytes[a * 2 : b * 2]
            if len(frag) >= 8:
                r = _rms_s16le_mono(frag)
            else:
                r = 0.0
            raw_rms.append(r)

        mx_r = max(raw_rms, default=0.0)
        self._viz_peak_follow = max(
            mx_r * 1.02,
            self._viz_peak_follow * 0.996,
            460.0,
        )
        cap = math.sqrt(max(self._viz_peak_follow, 280.0))
        normed = []
        for r in raw_rms:
            lvl = math.sqrt(max(0.0, r)) / cap
            lvl **= 0.88
            normed.append(max(0.06, min(1.0, lvl)))

        if self._viz_smooth is None or len(self._viz_smooth) != bands:
            self._viz_smooth = [0.1] * bands
        gamma = 0.38
        for i in range(bands):
            self._viz_smooth[i] = (
                gamma * normed[i] + (1.0 - gamma) * self._viz_smooth[i]
            )
        return list(self._viz_smooth), True

    def close(self) -> None:
        self.stop()
        self._wav_mono_cache.clear()
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None
        self._cache.clear()
