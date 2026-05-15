"""Command-line interface for the PRESENT package.

Exposed via ``python -m present <command>``.

Commands:
  init       Build the initial library (~200 songs).
  refresh    Re-run the pipeline, topping up failures and missing songs.
  add        Add a single song by artist + title.
  remove     Delete a song folder and drop it from the index.
  list       Print every song currently in the library.
  reindex    Rebuild ``data/index.json`` from per-song metadata.
  serve      Start the Flask web service.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import __version__
from . import pipeline
from .storage import Storage, make_song_id


def _stdout_log(msg: str) -> None:
    print(msg, flush=True)


def _progress_printer():
    last = {"line": ""}

    def progress(current: int, total: int) -> None:
        if total <= 0:
            return
        pct = 100 * current // max(1, total)
        line = f"[{current}/{total}] {pct}%"
        if line != last["line"]:
            last["line"] = line
            print(line, flush=True)

    return progress


def cmd_init(args: argparse.Namespace) -> int:
    storage = Storage(data_dir=args.data_dir)
    result = pipeline.initialize_library(
        target=args.target,
        bg_ratio=args.bg_ratio,
        storage=storage,
        log=_stdout_log,
        progress=_progress_printer(),
    )
    print(
        f"\nsuccess={result.success} skipped={result.skipped} "
        f"failed={result.failed}"
    )
    return 0 if result.failed == 0 else 1


def cmd_refresh(args: argparse.Namespace) -> int:
    storage = Storage(data_dir=args.data_dir)
    result = pipeline.refresh_library(
        target=args.target,
        bg_ratio=args.bg_ratio,
        storage=storage,
        log=_stdout_log,
        progress=_progress_printer(),
    )
    print(
        f"\nsuccess={result.success} skipped={result.skipped} "
        f"failed={result.failed}"
    )
    return 0 if result.failed == 0 else 1


def cmd_add(args: argparse.Namespace) -> int:
    storage = Storage(data_dir=args.data_dir)
    try:
        record = pipeline.add_song(
            artist=args.artist,
            title=args.title,
            origin=args.origin,
            storage=storage,
            log=_stdout_log,
            overwrite=args.overwrite,
        )
    except Exception as exc:  # noqa: BLE001 — surface single-song failure
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"added: {record.id}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    storage = Storage(data_dir=args.data_dir)
    song_id = args.song_id
    if "_-_" not in song_id and (args.artist and args.title):
        song_id = make_song_id(args.artist, args.title)
    ok = pipeline.remove_song(song_id, storage=storage, log=_stdout_log)
    return 0 if ok else 1


def cmd_list(args: argparse.Namespace) -> int:
    storage = Storage(data_dir=args.data_dir)
    songs = storage.list_songs()
    if not songs:
        print("(library is empty)")
        return 0
    bg_count = sum(1 for s in songs if s.get("origin") == "bg")
    glb_count = len(songs) - bg_count
    print(f"{len(songs)} songs ({bg_count} bg, {glb_count} global)\n")
    for s in songs:
        origin = s.get("origin", "?")
        duration = s.get("duration")
        dur = f"{duration:6.1f}s" if isinstance(duration, (int, float)) else "   ?  "
        print(f"  [{origin:>6}] {dur}  {s.get('artist','?')} — {s.get('title','?')}")
        if args.verbose:
            print(f"           id={s.get('id')}  yt={s.get('youtube_id')}")
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    storage = Storage(data_dir=args.data_dir)
    count = storage.rebuild_index_from_disk()
    print(f"reindexed: {count} songs")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from . import server  # imported lazily so flask isn't required for CLI-only use

    listen = f"http://{args.host}:{args.port}"
    if args.host in {"0.0.0.0", "::"}:
        print(
            f"PRESENT v{__version__} serving on all interfaces — {listen}",
            "(reachable from other devices on your LAN).",
            sep=" ",
        )
    else:
        print(f"PRESENT v{__version__} serving on {listen} (localhost only).")
    if args.data_dir:
        print(f"data dir: {args.data_dir}")
    server.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="present",
        description="Top-200 songs clip builder.",
    )
    parser.add_argument(
        "--version", action="version", version=f"present {__version__}"
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override the data directory (default: ./data).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Build the initial library.")
    p_init.add_argument("--target", type=int, default=200)
    p_init.add_argument("--bg-ratio", type=float, default=0.4)
    p_init.set_defaults(func=cmd_init)

    p_refresh = sub.add_parser(
        "refresh", help="Retry failures and top the library up to --target."
    )
    p_refresh.add_argument("--target", type=int, default=200)
    p_refresh.add_argument("--bg-ratio", type=float, default=0.4)
    p_refresh.set_defaults(func=cmd_refresh)

    p_add = sub.add_parser("add", help="Add a single song.")
    p_add.add_argument("artist")
    p_add.add_argument("title")
    p_add.add_argument(
        "--origin",
        choices=("bg", "global"),
        default="global",
    )
    p_add.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download and re-clip even if the song already exists.",
    )
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="Remove a song from the library.")
    p_remove.add_argument(
        "song_id",
        help="Song id (e.g. 'Taylor_Swift_-_Fortnight') or '<artist>' with --title.",
    )
    p_remove.add_argument("--artist", default=None)
    p_remove.add_argument("--title", default=None)
    p_remove.set_defaults(func=cmd_remove)

    p_list = sub.add_parser("list", help="List songs in the library.")
    p_list.add_argument("-v", "--verbose", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_reindex = sub.add_parser(
        "reindex", help="Rebuild data/index.json from per-song metadata."
    )
    p_reindex.set_defaults(func=cmd_reindex)

    p_serve = sub.add_parser("serve", help="Start the web service.")
    p_serve.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address. Default 0.0.0.0 = all interfaces (LAN). Use 127.0.0.1 for local only.",
    )
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--debug", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    try:
        return int(func(args) or 0)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
