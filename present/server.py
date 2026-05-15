"""Flask web service for the song library.

Public endpoints (no auth):
  GET  /                          → HTML library view
  GET  /api/songs                 → list of song summaries
  GET  /api/songs/<id>            → full per-song metadata
  GET  /api/songs/<id>/clip/<n>   → stream the Nth clip as M4A
  GET  /api/jobs                  → recent background jobs
  GET  /api/jobs/<id>             → single job, including log

Protected endpoints (require ``X-Auth-Token`` when ``PRESENT_TOKEN`` is
set in the environment / ``.env``):
  POST   /api/songs               → {"artist","title","origin"} — enqueue add
  POST   /api/songs/by_url        → {"artist","title","origin","url"}
  POST   /api/songs/bulk_delete    → {"ids":[...]} — remove many songs in one job
  DELETE /api/songs/<id>          → enqueue remove
  POST   /api/refresh             → enqueue library refresh
  POST   /api/init                → enqueue full (re)build

Admin UI:
  GET    /admin                   → song manager + add-by-URL form
  POST   /admin/login             → set the auth cookie
  POST   /admin/logout            → clear the auth cookie
"""

from __future__ import annotations

import os
from functools import wraps
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from . import pipeline
from .jobs import Job, get_queue
from .storage import PROJECT_ROOT, Storage, make_song_id


ENV_FILE = PROJECT_ROOT / ".env"


def _load_dotenv(path: Path = ENV_FILE) -> None:
    """Tiny `.env` loader (no python-dotenv dependency).

    Lines of the form ``KEY=value`` are added to ``os.environ`` only when
    the key is not already set. Quotes around values are stripped.
    """

    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    except OSError:
        pass


def _origin_label(origin: str) -> str:
    return {"bg": "Bulgarian", "global": "Global"}.get(origin, origin or "—")


def create_app(data_dir: Path | str | None = None) -> Flask:
    _load_dotenv()
    storage = Storage(data_dir=data_dir)

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["STORAGE"] = storage
    app.config["PRESENT_TOKEN"] = os.environ.get("PRESENT_TOKEN", "").strip()
    app.jinja_env.filters["origin_label"] = _origin_label

    queue = get_queue()

    # ------------------------------------------------------------ auth

    def _supplied_token() -> str:
        return (
            request.headers.get("X-Auth-Token")
            or request.args.get("token", "")
            or request.cookies.get("present_token", "")
        )

    def _token_ok() -> bool:
        expected = app.config.get("PRESENT_TOKEN") or ""
        return (not expected) or (_supplied_token() == expected)

    def require_token(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not _token_ok():
                return jsonify({"error": "unauthorized"}), 401
            return view(*args, **kwargs)

        return wrapper

    # ------------------------------------------------------------ views

    @app.get("/")
    def index() -> Any:
        songs = storage.list_songs()
        bg = [s for s in songs if s.get("origin") == "bg"]
        glb = [s for s in songs if s.get("origin") != "bg"]
        return render_template(
            "index.html",
            songs=songs,
            bg_songs=bg,
            global_songs=glb,
            total=len(songs),
            updated_at=storage.load_index().get("updated_at"),
            auth_required=bool(app.config.get("PRESENT_TOKEN")),
        )

    @app.get("/api/songs")
    def list_songs() -> Any:
        return jsonify({"songs": storage.list_songs()})

    @app.get("/api/songs/<song_id>")
    def song_detail(song_id: str) -> Any:
        meta = storage.read_metadata(song_id)
        if not meta:
            abort(404)
        return jsonify(meta)

    @app.get("/api/songs/<song_id>/clip/<int:clip_index>")
    def serve_clip(song_id: str, clip_index: int) -> Any:
        path = storage.clip_path(song_id, clip_index)
        if not path:
            abort(404)
        return send_file(
            path,
            mimetype="audio/mp4",
            as_attachment=False,
            download_name=f"{song_id}_clip_{clip_index}.m4a",
            conditional=True,
        )

    @app.get("/api/jobs")
    def list_jobs() -> Any:
        limit = max(1, min(100, int(request.args.get("limit", 20))))
        return jsonify(
            {"jobs": [j.to_dict(include_log=False) for j in queue.list_recent(limit)]}
        )

    @app.get("/api/jobs/<job_id>")
    def job_detail(job_id: str) -> Any:
        job = queue.get(job_id)
        if not job:
            abort(404)
        data = job.to_dict(include_log=True)
        qinfo = queue.job_queue_info(job_id)
        if qinfo:
            data["queue_position"] = qinfo["queue_position"]
            data["queue_length"] = qinfo["queue_length"]
        return jsonify(data)

    # ----------------------------------------------------------- writes

    @app.post("/api/songs")
    @require_token
    def add_song_endpoint() -> Any:
        payload = request.get_json(silent=True) or {}
        artist = str(payload.get("artist", "")).strip()
        title = str(payload.get("title", "")).strip()
        origin = str(payload.get("origin", "global")).strip().lower()
        overwrite = bool(payload.get("overwrite"))
        if not artist or not title:
            return jsonify({"error": "artist and title are required"}), 400
        if origin not in {"bg", "global"}:
            return jsonify({"error": "origin must be 'bg' or 'global'"}), 400

        def runner(job: Job):
            return pipeline.add_song(
                artist=artist,
                title=title,
                origin=origin,
                storage=storage,
                log=job.log,
                overwrite=overwrite,
            ).to_dict()

        job = queue.submit(
            "add",
            f"add {artist} - {title}",
            runner,
        )
        return jsonify({"job": job.to_dict(include_log=False)}), 202

    @app.post("/api/songs/by_url")
    @require_token
    def add_song_by_url_endpoint() -> Any:
        payload = request.get_json(silent=True) or {}
        artist = str(payload.get("artist", "")).strip()
        title = str(payload.get("title", "")).strip()
        url = str(payload.get("url", "")).strip()
        origin = str(payload.get("origin", "global")).strip().lower()
        overwrite = bool(payload.get("overwrite"))
        if not artist or not title or not url:
            return jsonify({"error": "artist, title and url are required"}), 400
        if origin not in {"bg", "global"}:
            return jsonify({"error": "origin must be 'bg' or 'global'"}), 400
        if "://" not in url:
            return jsonify({"error": "url must include http(s)://"}), 400

        def runner(job: Job):
            return pipeline.add_song_from_url(
                artist=artist,
                title=title,
                url=url,
                origin=origin,
                storage=storage,
                log=job.log,
                overwrite=overwrite,
            ).to_dict()

        job = queue.submit(
            "add_url",
            f"add {artist} - {title} (url)",
            runner,
        )
        return jsonify({"job": job.to_dict(include_log=False)}), 202

    _BULK_DELETE_MAX = 500

    @app.post("/api/songs/bulk_delete")
    @require_token
    def bulk_remove_songs_endpoint() -> Any:
        payload = request.get_json(silent=True) or {}
        raw = payload.get("ids")
        if not isinstance(raw, list):
            return jsonify({"error": "ids must be a non-empty array"}), 400
        ids = []
        seen: set[str] = set()
        for item in raw:
            sid = str(item).strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            ids.append(sid)
        if not ids:
            return jsonify({"error": "no song ids provided"}), 400
        if len(ids) > _BULK_DELETE_MAX:
            return jsonify(
                {"error": f"at most {_BULK_DELETE_MAX} songs per request"}
            ), 400

        def runner(job: Job) -> dict[str, Any]:
            removed = 0
            not_found = 0
            total = len(ids)
            for i, song_id in enumerate(ids, start=1):
                job.set_progress(i, total)
                ok = pipeline.remove_song(song_id, storage=storage, log=job.log)
                if ok:
                    removed += 1
                else:
                    not_found += 1
                    job.log(f"nothing to remove: {song_id}")
            return {
                "removed": removed,
                "not_found": not_found,
                "requested": total,
            }

        job = queue.submit(
            "bulk_remove",
            f"bulk remove {len(ids)} song(s)",
            runner,
        )
        return jsonify({"job": job.to_dict(include_log=False)}), 202

    @app.delete("/api/songs/<song_id>")
    @require_token
    def remove_song_endpoint(song_id: str) -> Any:
        if not storage.song_dir(song_id).exists():
            # Idempotent: 404 if it never existed.
            return jsonify({"error": "not found"}), 404

        def runner(job: Job):
            removed = pipeline.remove_song(song_id, storage=storage, log=job.log)
            return {"removed": removed, "id": song_id}

        job = queue.submit("remove", f"remove {song_id}", runner)
        return jsonify({"job": job.to_dict(include_log=False)}), 202

    @app.post("/api/refresh")
    @require_token
    def refresh_endpoint() -> Any:
        payload = request.get_json(silent=True) or {}
        target = int(payload.get("target", 200))
        bg_ratio = float(payload.get("bg_ratio", 0.4))

        def runner(job: Job):
            return pipeline.refresh_library(
                target=target,
                bg_ratio=bg_ratio,
                storage=storage,
                log=job.log,
                progress=job.set_progress,
            ).to_dict()

        job = queue.submit("refresh", f"refresh target={target}", runner)
        return jsonify({"job": job.to_dict(include_log=False)}), 202

    @app.post("/api/init")
    @require_token
    def init_endpoint() -> Any:
        payload = request.get_json(silent=True) or {}
        target = int(payload.get("target", 200))
        bg_ratio = float(payload.get("bg_ratio", 0.4))

        def runner(job: Job):
            return pipeline.initialize_library(
                target=target,
                bg_ratio=bg_ratio,
                storage=storage,
                log=job.log,
                progress=job.set_progress,
            ).to_dict()

        job = queue.submit("init", f"init target={target}", runner)
        return jsonify({"job": job.to_dict(include_log=False)}), 202

    # ------------------------------------------------------------ admin

    @app.get("/admin")
    def admin_page() -> Any:
        expected = app.config.get("PRESENT_TOKEN") or ""
        supplied = _supplied_token()
        if expected and supplied != expected:
            return render_template(
                "admin_login.html",
                error=request.args.get("error") or "",
            )
        songs = storage.list_songs()
        bg = [s for s in songs if s.get("origin") == "bg"]
        glb = [s for s in songs if s.get("origin") != "bg"]
        resp = make_response(
            render_template(
                "admin.html",
                songs=songs,
                bg_songs=bg,
                global_songs=glb,
                total=len(songs),
                updated_at=storage.load_index().get("updated_at"),
                token=supplied,
                auth_required=bool(expected),
            )
        )
        if expected and supplied:
            # Refresh cookie so the session sticks across navigation.
            resp.set_cookie(
                "present_token",
                supplied,
                httponly=False,
                samesite="Lax",
                max_age=60 * 60 * 12,
            )
        return resp

    @app.post("/admin/login")
    def admin_login() -> Any:
        token = (request.form.get("token") or "").strip()
        expected = app.config.get("PRESENT_TOKEN") or ""
        if expected and token != expected:
            return redirect(url_for("admin_page", error="bad_token"))
        resp = make_response(redirect(url_for("admin_page")))
        if expected:
            resp.set_cookie(
                "present_token",
                token,
                httponly=False,
                samesite="Lax",
                max_age=60 * 60 * 12,
            )
        return resp

    @app.post("/admin/logout")
    def admin_logout() -> Any:
        resp = make_response(redirect(url_for("admin_page")))
        resp.delete_cookie("present_token")
        return resp

    # ---------------------------------------------------------- helpers

    @app.errorhandler(404)
    def not_found(_exc):  # type: ignore[override]
        if request.path.startswith("/api/"):
            return jsonify({"error": "not found"}), 404
        return render_template("index.html",
                               songs=[],
                               bg_songs=[],
                               global_songs=[],
                               total=0,
                               updated_at=None,
                               auth_required=bool(app.config.get("PRESENT_TOKEN")),
                               message="Page not found."), 404

    @app.get("/healthz")
    def healthz() -> Any:
        return {"ok": True, "songs": len(storage.list_songs())}

    # silence unused warning if make_song_id ever becomes needed here
    _ = make_song_id

    return app


def run(host: str = "0.0.0.0", port: int = 8080, debug: bool = False) -> None:
    app = create_app()
    app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)
