"""File-backed project store.

Each project is a directory:

    workspace/projects/<project-id>/
        input/          original uploads, never modified
        assets/         thumbnails, filmstrips, analysis images
        intermediate/   video-use edit dir: edl.json, transcripts/, clips, logs
        output/         version-001.mp4, version-002.mp4, ...
        project.json    all project metadata

project.json is written atomically (temp file + os.replace) under a
per-project lock, so a crash mid-write never leaves a torn file.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from .config import settings
from .security import check_id, clean_text, new_id, safe_join

SCHEMA_VERSION = 1
SUBDIRS = ("input", "assets", "intermediate", "output")

DEFAULT_RENDER_SETTINGS: dict[str, Any] = {
    "resolution": "1080p",   # original | 1080p | 4k
    "aspect": "source",      # source | 16:9 | 9:16 | 1:1
    "fps": "source",         # source | 24 | 25 | 30 | 60
    "quality": "high",       # preview | high | maximum
    # Advanced
    "grade": "none",         # none | subtle | neutral_punch | warm_cinematic | auto (video-use grade.py)
    "fit": "crop",           # crop (fill frame) | letterbox (fit inside)
    "audio": "keep",         # keep | mute
    "loudnorm": True,        # video-use two-pass loudnorm when audio is present
    "burn_labels": False,    # minimal room-label typography from segment labels
}

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def now() -> float:
    return round(time.time(), 3)


def _lock(pid: str) -> threading.RLock:
    with _locks_guard:
        if pid not in _locks:
            _locks[pid] = threading.RLock()
        return _locks[pid]


def project_dir(pid: str) -> Path:
    check_id(pid, "project")
    return safe_join(settings.projects_dir, pid)


def project_subdir(pid: str, sub: str) -> Path:
    assert sub in SUBDIRS
    return project_dir(pid) / sub


def _meta_path(pid: str) -> Path:
    return project_dir(pid) / "project.json"


def _write_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load(pid: str) -> dict:
    path = _meta_path(pid)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="unknown project")
    with _lock(pid):
        return json.loads(path.read_text(encoding="utf-8"))


def update(pid: str, fn: Callable[[dict], Any]) -> dict:
    """Load, mutate in place with `fn`, bump updated_at, save. Returns the project."""
    with _lock(pid):
        project = load(pid)
        fn(project)
        project["updated_at"] = now()
        _write_atomic(_meta_path(pid), project)
        return project


def create(name: str) -> dict:
    pid = new_id("p")
    pdir = safe_join(settings.projects_dir, pid)
    for sub in SUBDIRS:
        (pdir / sub).mkdir(parents=True, exist_ok=True)
    ts = now()
    project = {
        "schema": SCHEMA_VERSION,
        "id": pid,
        "name": clean_text(name, 120) or "Untitled Project",
        "created_at": ts,
        "updated_at": ts,
        "preset": None,
        "prompt": "",
        "target_duration": None,
        "media": [],
        "analysis": {"status": "none", "clips": {}, "notes": [], "updated_at": None},
        "plan": {"status": "none", "segments": []},
        "render_settings": dict(DEFAULT_RENDER_SETTINGS),
        "jobs": [],
        "outputs": [],
    }
    with _lock(pid):
        _write_atomic(pdir / "project.json", project)
    return project


def list_projects() -> list[dict]:
    root = settings.projects_dir
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        meta = d / "project.json"
        if not meta.is_file():
            continue
        try:
            p = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "id": p["id"],
            "name": p.get("name", "Untitled"),
            "created_at": p.get("created_at"),
            "updated_at": p.get("updated_at"),
            "media_count": len(p.get("media", [])),
            "output_count": len(p.get("outputs", [])),
            "thumbnail": _first_thumb(p),
        })
    out.sort(key=lambda x: x.get("updated_at") or 0, reverse=True)
    return out


def _first_thumb(p: dict) -> str | None:
    for m in p.get("media", []):
        if m.get("thumbnail"):
            return f"/api/projects/{p['id']}/media/{m['id']}/thumbnail"
    return None


def delete(pid: str) -> None:
    pdir = project_dir(pid)
    if not (pdir / "project.json").is_file():
        raise HTTPException(status_code=404, detail="unknown project")
    with _lock(pid):
        shutil.rmtree(pdir)


def recover_interrupted_jobs() -> None:
    """On startup, any job still marked running/queued died with the old process."""
    root = settings.projects_dir
    if not root.is_dir():
        return
    for d in root.iterdir():
        if not (d / "project.json").is_file():
            continue

        def fix(p: dict) -> None:
            for job in p.get("jobs", []):
                if job.get("status") in ("queued", "running"):
                    job["status"] = "error"
                    job["error"] = "Interrupted: the server restarted while this job was running."
                    job["finished_at"] = now()
            if p.get("analysis", {}).get("status") == "running":
                p["analysis"]["status"] = "error"

        try:
            update(d.name, fix)
        except HTTPException:
            continue
