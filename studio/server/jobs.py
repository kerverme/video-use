"""Minimal local job system.

Long work (analysis, planning, rendering) runs on a background thread pool,
never on the request thread. Job state lives inside project.json (`jobs`), so
the UI simply polls the project and a server restart can mark interrupted jobs
as failed. One active job per project keeps state simple and predictable.
"""

from __future__ import annotations

import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from fastapi import HTTPException

from . import store
from .security import new_id

MAX_JOB_HISTORY = 25
_PROGRESS_WRITE_INTERVAL_S = 0.5

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cv-job")
_active: dict[str, "JobContext"] = {}  # project id -> running job
_active_lock = threading.Lock()


class ConfigurationRequired(Exception):
    """A required service (e.g. the AI planner key) is not configured."""


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, pid: str, job_id: str, stages: list[str]):
        self.pid = pid
        self.job_id = job_id
        self.stages = stages
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._last_write = 0.0

    # -- state -------------------------------------------------------------
    def _patch(self, **fields) -> None:
        def fn(p: dict) -> None:
            for job in p["jobs"]:
                if job["id"] == self.job_id:
                    job.update(fields)
                    break
        store.update(self.pid, fn)

    def stage(self, name: str, message: str | None = None) -> None:
        self.check_cancel()
        self._patch(stage=name, progress=None, message=message)

    def progress(self, fraction: float | None, message: str | None = None, force: bool = False) -> None:
        t = time.monotonic()
        if not force and t - self._last_write < _PROGRESS_WRITE_INTERVAL_S:
            return
        self._last_write = t
        fields: dict = {"progress": None if fraction is None else round(max(0.0, min(1.0, fraction)), 4)}
        if message is not None:
            fields["message"] = message
        self._patch(**fields)

    # -- cancellation --------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()

    def check_cancel(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    # -- subprocess helper ---------------------------------------------------
    def run(self, cmd: list[str], on_line: Callable[[str], None] | None = None,
            cwd: str | None = None, env: dict | None = None, timeout: float | None = None) -> str:
        """Run a command (argument list — never a shell string). Returns combined output tail."""
        self.check_cancel()
        tail: list[str] = []
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            cwd=cwd, env=env, bufsize=1, errors="replace",
        )
        started = time.monotonic()
        try:
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                line = line.rstrip()
                tail.append(line)
                if len(tail) > 60:
                    tail.pop(0)
                if on_line:
                    on_line(line)
                if self._cancel.is_set():
                    self._proc.terminate()
                if timeout and time.monotonic() - started > timeout:
                    self._proc.kill()
                    raise RuntimeError(f"{cmd[0]} timed out")
            code = self._proc.wait()
        finally:
            self._proc = None
        self.check_cancel()
        if code != 0:
            raise RuntimeError(f"{cmd[0]} failed (exit {code}): " + " | ".join(tail[-6:]))
        return "\n".join(tail)


def active_job(pid: str) -> JobContext | None:
    with _active_lock:
        return _active.get(pid)


def submit(pid: str, kind: str, stages: list[str], work: Callable[[JobContext], dict | None]) -> dict:
    with _active_lock:
        if pid in _active:
            raise HTTPException(status_code=409, detail="Another job is already running for this project.")
        job_id = new_id("j")
        ctx = JobContext(pid, job_id, stages)
        _active[pid] = ctx

    job = {
        "id": job_id, "kind": kind, "status": "queued", "stages": stages,
        "stage": None, "progress": None, "message": None, "error": None,
        "result": None, "created_at": store.now(), "started_at": None, "finished_at": None,
    }

    def add(p: dict) -> None:
        p["jobs"].append(job)
        del p["jobs"][:-MAX_JOB_HISTORY]

    try:
        store.update(pid, add)
    except Exception:
        with _active_lock:
            _active.pop(pid, None)
        raise

    def runner() -> None:
        ctx._patch(status="running", started_at=store.now())
        try:
            result = work(ctx)
            ctx._patch(status="done", progress=1.0, result=result, finished_at=store.now(), stage="Complete")
        except JobCancelled:
            ctx._patch(status="cancelled", finished_at=store.now(), message="Cancelled")
        except ConfigurationRequired as exc:
            ctx._patch(status="config_required", error=str(exc), finished_at=store.now())
        except Exception as exc:  # surfaced to the UI; full trace to server log
            traceback.print_exc()
            ctx._patch(status="error", error=str(exc)[:2000], finished_at=store.now())
        finally:
            with _active_lock:
                _active.pop(pid, None)

    _executor.submit(runner)
    return job


def cancel(pid: str) -> bool:
    ctx = active_job(pid)
    if not ctx:
        return False
    ctx.cancel()
    return True
