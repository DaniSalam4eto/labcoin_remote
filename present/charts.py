"""Best-effort chart scrapers and the offline seed loader.

The chart scrapers are intentionally tolerant: every page that fails or
returns nothing is logged and skipped, and the caller will fall back to
``seed_songs.json``. We deliberately avoid third-party HTML parsing
dependencies — a handful of regular expressions over the rendered page
is enough to extract artist/title pairs.

Each candidate is a dict with at least ``artist``, ``title`` and
``origin`` keys (``"bg"`` for Bulgarian charts, ``"global"`` otherwise).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path
from typing import Callable, Iterable

from .storage import PROJECT_ROOT, make_song_id

SEED_PATH = PROJECT_ROOT / "seed_songs.json"

LogFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,bg;q=0.8",
}


def _http_get(url: str, timeout: float = 12.0) -> str | None:
    req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


# --------------------------------------------------------------------- seed


def load_seed(path: Path = SEED_PATH) -> list[dict[str, str]]:
    """Read ``seed_songs.json``; return an empty list if missing/broken."""

    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    songs = data.get("songs") if isinstance(data, dict) else data
    if not isinstance(songs, list):
        return []
    out: list[dict[str, str]] = []
    for entry in songs:
        if not isinstance(entry, dict):
            continue
        artist = str(entry.get("artist", "")).strip()
        title = str(entry.get("title", "")).strip()
        origin = str(entry.get("origin", "global")).strip().lower()
        if not artist or not title:
            continue
        if origin not in {"bg", "global"}:
            origin = "global"
        out.append(
            {
                "artist": artist,
                "title": title,
                "origin": origin,
                "source": "seed",
            }
        )
    return out


# ------------------------------------------------------------------- scrapers


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def fetch_billboard_hot100(log: LogFn = _noop) -> list[dict[str, str]]:
    """Scrape the public Billboard Hot 100 page (best-effort)."""

    html = _http_get("https://www.billboard.com/charts/hot-100/")
    if not html:
        log("billboard: page fetch failed")
        return []

    pattern = re.compile(
        r'<h3[^>]+id="title-of-a-story"[^>]*>(?P<title>.*?)</h3>'
        r'.*?<span[^>]+class="[^"]*c-label[^"]*"[^>]*>(?P<artist>.*?)</span>',
        re.DOTALL,
    )
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for match in pattern.finditer(html):
        title = _strip_html(match.group("title"))
        artist = _strip_html(match.group("artist"))
        if not title or not artist:
            continue
        key = (artist.lower(), title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "artist": artist,
                "title": title,
                "origin": "global",
                "source": "billboard",
            }
        )
        if len(out) >= 100:
            break
    log(f"billboard: parsed {len(out)} entries")
    return out


def fetch_bgtop40(log: LogFn = _noop) -> list[dict[str, str]]:
    """Scrape bgtop40.com radio chart (Bulgarian top-40)."""

    html = _http_get("https://bgtop40.com/")
    if not html:
        log("bgtop40: page fetch failed")
        return []
    # The site lists entries roughly as: "<n>. Artist - Title"
    pattern = re.compile(
        r"(?:^|>)\s*\d{1,3}\.\s*([^<\n\r-]{2,60})\s*[-–]\s*([^<\n\r]{2,80})",
        re.MULTILINE,
    )
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for match in pattern.finditer(html):
        artist = _strip_html(match.group(1))
        title = _strip_html(match.group(2))
        if not artist or not title:
            continue
        if len(artist) > 60 or len(title) > 80:
            continue
        key = (artist.lower(), title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "artist": artist,
                "title": title,
                "origin": "bg",
                "source": "bgtop40",
            }
        )
        if len(out) >= 40:
            break
    log(f"bgtop40: parsed {len(out)} entries")
    return out


# ------------------------------------------------------------------ pipeline


def dedupe(candidates: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Deduplicate by song id (which derives from artist + title)."""

    seen: dict[str, dict[str, str]] = {}
    for c in candidates:
        sid = make_song_id(c["artist"], c["title"])
        prior = seen.get(sid)
        if prior is None:
            seen[sid] = c
            continue
        # Prefer scraped chart entries over seed entries for freshness.
        if prior.get("source") == "seed" and c.get("source") != "seed":
            seen[sid] = c
    return list(seen.values())


def balance(
    candidates: list[dict[str, str]],
    target: int,
    bg_ratio: float,
) -> list[dict[str, str]]:
    """Interleave BG and global candidates to hit a target ratio.

    Keeps the original order within each bucket so chart-derived hits
    stay near the top.
    """

    if target <= 0:
        return []
    bg_target = max(0, round(target * bg_ratio))
    global_target = max(0, target - bg_target)

    bg = [c for c in candidates if c.get("origin") == "bg"]
    glb = [c for c in candidates if c.get("origin") != "bg"]

    chosen: list[dict[str, str]] = []
    chosen.extend(bg[:bg_target])
    chosen.extend(glb[:global_target])

    # Backfill if either bucket was thin so we still aim for `target`.
    if len(chosen) < target:
        extras_bg = bg[bg_target:]
        extras_glb = glb[global_target:]
        i = j = 0
        while len(chosen) < target and (i < len(extras_bg) or j < len(extras_glb)):
            if i < len(extras_bg):
                chosen.append(extras_bg[i])
                i += 1
                if len(chosen) >= target:
                    break
            if j < len(extras_glb):
                chosen.append(extras_glb[j])
                j += 1
    return chosen[:target]


def gather_candidates(
    target: int = 200,
    bg_ratio: float = 0.4,
    log: LogFn = _noop,
) -> list[dict[str, str]]:
    """Combine live chart scrapes with the offline seed, then balance."""

    scraped: list[dict[str, str]] = []
    for fn in (fetch_bgtop40, fetch_billboard_hot100):
        try:
            scraped.extend(fn(log=log))
        except Exception as exc:  # noqa: BLE001 — best-effort scraping
            log(f"{fn.__name__}: error {exc}")

    seeded = load_seed()
    log(f"seed: loaded {len(seeded)} entries")

    merged = dedupe(scraped + seeded)
    log(f"merged: {len(merged)} unique candidates")
    return balance(merged, target, bg_ratio)
