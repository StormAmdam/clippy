"""Job records (clip jobs and autopilot runs), persisted so history survives restarts.

States: queued → running → done | error | cancelled.  A job that was queued or running when the
server stopped comes back as "interrupted".
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

KEEP_JOBS = 60      # finished jobs remembered
KEEP_LOG = 80       # log lines persisted per job
LIVE = ("queued", "running")


class Cancelled(Exception):
    """Raised inside a running job at its next progress update after the user pressed Cancel."""


class JobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._last_save = 0.0
        try:
            saved = json.loads(self.path.read_text())
        except (OSError, ValueError):
            saved = []
        if not isinstance(saved, list):   # a damaged history file must never stop Clippy from starting
            saved = []
        for job in saved:
            if not isinstance(job, dict) or not job.get("id"):
                continue
            job.setdefault("created", job.get("finished") or 0.0)
            if job.get("state") in LIVE:
                job.update(state="interrupted", msg="Stopped because Clippy was closed",
                           finished=job.get("finished") or time.time())
            self._jobs[job["id"]] = job

    # ── reading
    # callers get copies: the worker keeps changing the real dicts while requests serialise them
    def get(self, jid: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(jid)
            return dict(job) if job else None

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(j) for j in sorted(self._jobs.values(), key=lambda j: -j["created"])]

    # ── writing
    def create(self, **fields) -> dict:
        job = {"id": uuid.uuid4().hex[:10], "kind": "clip", "url": "", "options": {}, "state": "queued",
               "stage": "queued", "pct": 0.0, "msg": "Waiting in line…", "log": [], "created": time.time(),
               "result": None, "error": None, "cancel_requested": False, **fields}
        with self._lock:
            self._jobs[job["id"]] = job
            self._save(force=True)
            return dict(job)

    def update(self, jid: str, **fields) -> dict:
        with self._lock:
            job = self._jobs[jid]
            job.update(fields)
            self._save(force="state" in fields)
            return dict(job)

    def start(self, jid: str) -> bool:
        """queued → running in one step, so a Cancel can't land in between. False if it shouldn't run."""
        with self._lock:
            job = self._jobs.get(jid)
            if not job or job["state"] != "queued":
                return False
            job.update(state="running", started=time.time())
            self._save(force=True)
            return True

    def request_cancel(self, jid: str) -> bool:
        with self._lock:
            job = self._jobs.get(jid)
            if not job or job["state"] not in LIVE:
                return False
            if job["state"] == "queued":
                job.update(state="cancelled", msg="Cancelled", finished=time.time())
            else:
                job.update(cancel_requested=True, msg="Cancelling…")
            self._save(force=True)
            return True

    def progress_fn(self, jid: str):
        def progress(stage: str, pct: float, msg: str = "") -> None:
            with self._lock:
                job = self._jobs[jid]
                if job.get("cancel_requested"):
                    raise Cancelled()
                job.update(stage=stage, pct=round(pct, 4), msg=msg or job["msg"], updated=time.time())
                self._save()
        return progress

    def log_fn(self, jid: str):
        def log(msg) -> None:
            with self._lock:
                job = self._jobs[jid]
                job["log"] = (job["log"] + [str(msg)])[-300:]
                self._save()
        return log

    def _save(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_save < 3:
            return
        self._last_save = now
        jobs = sorted(self._jobs.values(), key=lambda j: j["created"])
        finished = [j for j in jobs if j["state"] not in LIVE]
        for old in finished[:-KEEP_JOBS] if len(finished) > KEEP_JOBS else []:
            self._jobs.pop(old["id"], None)
        data = [{**j, "log": j["log"][-KEEP_LOG:]} for j in sorted(self._jobs.values(), key=lambda j: j["created"])]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, default=str))
            os.replace(tmp, self.path)
        except OSError:
            pass  # history is a convenience; never break a job over it
