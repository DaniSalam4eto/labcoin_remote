"""In-memory background job queue used by the web service.

The HTTP layer hands long-running operations (init, refresh, add) to
this queue and returns the job id immediately. Multiple worker threads
drain the queue in parallel so several clip downloads / encodes can
proceed at once. Set ``PRESENT_PARALLEL_JOBS`` (1–16, default 4) to cap
concurrency — useful on low-power hosts.

Index updates in :class:`present.storage.Storage` are locked so parallel
finishing jobs do not corrupt ``data/index.json``.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque

JobRunner = Callable[["Job"], Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Job:
    """One unit of work tracked by :class:`JobQueue`.

    The ``runner`` receives the job itself so it can append log lines and
    update progress as work proceeds.
    """

    id: str
    type: str
    description: str
    runner: JobRunner | None = None
    status: str = "queued"  # queued | running | done | failed | cancelled
    created_at: str = field(default_factory=_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    progress: int = 0
    total: int = 0
    log_lines: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def log(self, message: str) -> None:
        line = f"[{_now_iso()}] {message}"
        with self._lock:
            self.log_lines.append(line)
            # Cap log size to keep the in-memory footprint sane.
            if len(self.log_lines) > 2000:
                del self.log_lines[: len(self.log_lines) - 2000]

    def set_progress(self, current: int, total: int) -> None:
        with self._lock:
            self.progress = current
            self.total = total

    def to_dict(self, include_log: bool = True) -> dict[str, Any]:
        with self._lock:
            data = {
                "id": self.id,
                "type": self.type,
                "description": self.description,
                "status": self.status,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "progress": self.progress,
                "total": self.total,
                "result": self.result,
                "error": self.error,
            }
            if include_log:
                data["log"] = list(self.log_lines)
            return data


class JobQueue:
    """FIFO queue with one or more worker threads and bounded history.

    Thread-safe; intended to be used as a module-level singleton. Call
    :meth:`start` once before submitting work.
    """

    def __init__(self, history: int = 400, workers: int | None = None) -> None:
        if workers is None:
            raw = os.environ.get("PRESENT_PARALLEL_JOBS", "4").strip()
            try:
                workers = int(raw)
            except ValueError:
                workers = 4
        self._workers = max(1, min(16, workers))
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._queue: Deque[Job] = deque()
        self._all: dict[str, Job] = {}
        self._order: Deque[str] = deque()
        self._history = history
        self._worker_threads: list[threading.Thread] = []
        self._stop = threading.Event()

    def start(self) -> None:
        with self._lock:
            if self._worker_threads and any(t.is_alive() for t in self._worker_threads):
                return
            self._stop.clear()
            self._worker_threads = []
            for i in range(self._workers):
                t = threading.Thread(
                    target=self._run, name=f"present-jobs-{i}", daemon=True
                )
                t.start()
                self._worker_threads.append(t)

    def stop(self, timeout: float | None = 5.0) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        per = None
        if timeout is not None and self._worker_threads:
            per = max(0.1, timeout / len(self._worker_threads))
        for t in self._worker_threads:
            t.join(timeout=per)

    def submit(self, type_: str, description: str, runner: JobRunner) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            type=type_,
            description=description,
            runner=runner,
        )
        with self._cv:
            self._queue.append(job)
            self._all[job.id] = job
            self._order.append(job.id)
            self._trim()
            # Wake every idle worker so a backlog clears quickly after bursts.
            self._cv.notify_all()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._all.get(job_id)

    def job_queue_info(self, job_id: str) -> dict[str, int] | None:
        """When the job is still queued, return its 1-based position and queue length."""

        with self._lock:
            job = self._all.get(job_id)
            if not job or job.status != "queued":
                return None
            pending = list(self._queue)
            for idx, j in enumerate(pending):
                if j.id == job_id:
                    return {"queue_position": idx + 1, "queue_length": len(pending)}
            return None

    def list_recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            ids = list(self._order)[-limit:][::-1]
            return [self._all[i] for i in ids if i in self._all]

    # ---- internals --------------------------------------------------

    def _trim(self) -> None:
        while len(self._order) > self._history:
            oldest = self._order.popleft()
            job = self._all.get(oldest)
            if job and job.status in {"queued", "running"}:
                # Don't drop active jobs from the registry.
                self._order.append(oldest)
                break
            self._all.pop(oldest, None)

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                while not self._queue and not self._stop.is_set():
                    self._cv.wait(timeout=1.0)
                if self._stop.is_set():
                    return
                job = self._queue.popleft()
            self._execute(job)

    def _execute(self, job: Job) -> None:
        job.status = "running"
        job.started_at = _now_iso()
        job.log(f"start: {job.type}")
        try:
            if job.runner is None:
                raise RuntimeError("job has no runner")
            result = job.runner(job)
            if result is None:
                job.result = None
            elif isinstance(result, dict):
                job.result = result
            else:
                # Coerce dataclasses with .to_dict() or fall back to repr.
                to_dict = getattr(result, "to_dict", None)
                job.result = to_dict() if callable(to_dict) else {"value": repr(result)}
            job.status = "done"
            job.log("done")
        except Exception as exc:  # noqa: BLE001 — surface as failure
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.log(f"FAILED: {job.error}")
        finally:
            job.finished_at = _now_iso()


_singleton: JobQueue | None = None
_singleton_lock = threading.Lock()


def get_queue() -> JobQueue:
    """Return the process-wide :class:`JobQueue` (creates + starts it)."""

    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = JobQueue()
            _singleton.start()
        return _singleton
