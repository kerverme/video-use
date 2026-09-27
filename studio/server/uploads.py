"""Chunked, resumable uploads for large video files.

Protocol (all under /api/projects/<pid>/uploads):

    POST   ""                    {filename, size}  -> {upload_id, chunk_size, offset}
    PUT    "/<uid>?offset=N"     raw bytes (one chunk) -> {offset}
    GET    "/<uid>"              -> {offset, size}   (resume after a dropped connection)
    POST   "/<uid>/complete"     -> media item (validated, probed, thumbnailed)
    DELETE "/<uid>"              cancel

Chunks are streamed straight from the request body to a `.part` file on disk,
so memory use is one network buffer regardless of file size. A chunk must
start exactly at the current end of the part file, which makes retries
idempotent and resumption trivial. Staging lives in workspace/temp/uploads on
the same filesystem as the projects, so completion is an atomic rename.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request

from . import media, store
from .config import settings
from .security import (
    check_id, clean_text, is_allowed_video_name, looks_like_iso_bmff,
    new_id, safe_join, sanitize_filename,
)

STALE_UPLOAD_S = 48 * 3600
_state_lock = threading.Lock()


def _paths(uid: str) -> tuple[Path, Path]:
    check_id(uid, "upload")
    root = settings.uploads_tmp_dir
    return safe_join(root, f"{uid}.part"), safe_join(root, f"{uid}.json")


def _read_state(uid: str) -> dict:
    _, meta = _paths(uid)
    if not meta.is_file():
        raise HTTPException(status_code=404, detail="unknown upload")
    return json.loads(meta.read_text())


def start(pid: str, filename: str, size: int) -> dict:
    store.load(pid)  # 404 if the project is missing
    if not is_allowed_video_name(filename):
        raise HTTPException(status_code=415, detail="Only .mp4 and .mov files are supported.")
    if not isinstance(size, int) or size <= 0:
        raise HTTPException(status_code=400, detail="invalid file size")
    if size > settings.max_upload_bytes:
        limit_gb = settings.max_upload_bytes / 1024**3
        raise HTTPException(status_code=413, detail=f"File exceeds the {limit_gb:.0f} GB upload limit.")
    settings.uploads_tmp_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(settings.uploads_tmp_dir).free
    if size + settings.min_free_bytes > free:
        raise HTTPException(status_code=507, detail="Not enough free disk space for this file.")

    uid = new_id("u")
    part, meta = _paths(uid)
    part.touch()
    meta.write_text(json.dumps({
        "upload_id": uid, "project_id": pid, "filename": sanitize_filename(filename),
        "original_name": clean_text(filename, 200), "size": size, "created_at": time.time(),
    }))
    return {"upload_id": uid, "chunk_size": settings.chunk_bytes, "offset": 0}


def status(pid: str, uid: str) -> dict:
    st = _read_state(uid)
    if st["project_id"] != pid:
        raise HTTPException(status_code=404, detail="unknown upload")
    part, _ = _paths(uid)
    return {"upload_id": uid, "offset": part.stat().st_size if part.exists() else 0, "size": st["size"]}


async def write_chunk(pid: str, uid: str, offset: int, request: Request) -> dict:
    st = _read_state(uid)
    if st["project_id"] != pid:
        raise HTTPException(status_code=404, detail="unknown upload")
    part, _ = _paths(uid)
    current = part.stat().st_size
    if offset != current:
        # Client and server disagree (e.g. a retried chunk that already landed).
        raise HTTPException(status_code=409, detail={"message": "offset mismatch", "offset": current})

    max_chunk = settings.chunk_bytes * 2
    written = 0
    with open(part, "ab") as f:
        async for block in request.stream():
            written += len(block)
            if written > max_chunk or current + written > st["size"]:
                f.truncate(current)
                raise HTTPException(status_code=413, detail="chunk too large")
            f.write(block)
    return {"offset": current + written}


def cancel(pid: str, uid: str) -> None:
    st = _read_state(uid)
    if st["project_id"] != pid:
        raise HTTPException(status_code=404, detail="unknown upload")
    for p in _paths(uid):
        p.unlink(missing_ok=True)


def _unique_name(directory: Path, filename: str) -> str:
    stem, dot, ext = filename.rpartition(".")
    candidate, n = filename, 2
    while (directory / candidate).exists():
        candidate = f"{stem}-{n}.{ext}"
        n += 1
    return candidate


def complete(pid: str, uid: str) -> dict:
    st = _read_state(uid)
    if st["project_id"] != pid:
        raise HTTPException(status_code=404, detail="unknown upload")
    part, meta = _paths(uid)
    if part.stat().st_size != st["size"]:
        raise HTTPException(status_code=409, detail="upload incomplete")

    def reject(msg: str) -> None:
        part.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=msg)

    if not looks_like_iso_bmff(part):
        reject("This file is not a valid MP4/MOV container.")
    try:
        info = media.probe(part)
    except media.ProbeError as exc:
        reject(str(exc))

    input_dir = store.project_subdir(pid, "input")
    with _state_lock:
        stored_name = _unique_name(input_dir, st["filename"])
        dest = safe_join(input_dir, stored_name)
        os.replace(part, dest)  # same filesystem → atomic, no copy
    meta.unlink(missing_ok=True)
    # Originals are read-only from here on.
    os.chmod(dest, 0o444)

    mid = new_id("m")
    thumb_name = f"thumb_{mid}.jpg"
    has_thumb = media.make_thumbnail(dest, store.project_subdir(pid, "assets") / thumb_name, info["duration"])
    display = st["original_name"].rsplit(".", 1)[0] or stored_name
    item = {
        "id": mid,
        "file": stored_name,
        "display_name": clean_text(display, 120),
        "original_name": st["original_name"],
        "size": st["size"],
        "added_at": store.now(),
        "status": "ready",
        "meta": info,
        "thumbnail": thumb_name if has_thumb else None,
    }

    def add(p: dict) -> None:
        p["media"].append(item)
        # New media invalidates earlier analysis.
        if p["analysis"].get("status") == "done":
            p["analysis"]["status"] = "stale"

    store.update(pid, add)
    return item


def sweep_stale() -> None:
    """Remove abandoned partial uploads older than STALE_UPLOAD_S."""
    root = settings.uploads_tmp_dir
    if not root.is_dir():
        return
    cutoff = time.time() - STALE_UPLOAD_S
    for p in root.iterdir():
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
        except OSError:
            pass
