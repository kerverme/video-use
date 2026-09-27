"""CLOUD VIDEO: FastAPI server.

Serves the JSON API under /api and the statically exported Next.js frontend
(studio/web/out) at /, on a single port. A single origin means no proxy sits
between the browser and the chunked upload endpoint.

Run:  studio/run.sh   (or: uvicorn server.main:app --host 0.0.0.0 --port 8000)
"""

from __future__ import annotations

import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, engine, jobs, planner, store, uploads
from .config import (WEB_OUT_DIR, anthropic_configured, elevenlabs_key, ensure_dirs, settings)
from .presets import PRESETS, public_presets
from .security import check_id, clean_text, safe_join
from .timing import compute_timeline


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_dirs()
    store.recover_interrupted_jobs()
    uploads.sweep_stale()
    yield


app = FastAPI(title="CLOUD VIDEO", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.middleware("http")(auth.middleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'",
    )
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# ---------------------------------------------------------------- helpers

def _tool_version(cmd: str) -> str | None:
    if not shutil.which(cmd):
        return None
    try:
        out = subprocess.run([cmd, "-version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = out.splitlines()[0] if out else ""
    parts = first.split()
    return parts[2] if len(parts) > 2 else first or None


def _serialize(project: dict) -> dict:
    pid = project["id"]
    p = dict(project)
    base = f"/api/projects/{pid}"
    p["media"] = []
    for m in project["media"]:
        m = dict(m)
        m["thumbnail_url"] = f"{base}/media/{m['id']}/thumbnail" if m.get("thumbnail") else None
        m["file_url"] = f"{base}/media/{m['id']}/file"
        clip = project["analysis"].get("clips", {}).get(m["id"], {})
        m["filmstrip_url"] = f"{base}/media/{m['id']}/filmstrip" if clip.get("filmstrip") else None
        m["scene_count"] = len(clip.get("scenes", [])) if clip else None
        p["media"].append(m)
    plan = dict(project["plan"])
    timeline, total = compute_timeline(plan.get("segments", []))
    plan["segments"] = [dict(s, **t) for s, t in zip(plan.get("segments", []), timeline)]
    plan["total_duration"] = total
    p["plan"] = plan
    # Analysis internals (keyframe file lists) stay server-side.
    p["analysis"] = {k: v for k, v in project["analysis"].items() if k != "clips"}
    p["outputs"] = [dict(o, file_url=f"{base}/outputs/{o['id']}/file",
                         download_url=f"{base}/outputs/{o['id']}/file?download=1",
                         thumbnail_url=f"{base}/outputs/{o['id']}/thumbnail")
                    for o in sorted(project["outputs"], key=lambda o: o["version"], reverse=True)]
    active = jobs.active_job(pid)
    p["active_job"] = next((j for j in reversed(project["jobs"]) if active and j["id"] == active.job_id), None)
    p["last_job"] = project["jobs"][-1] if project["jobs"] else None
    p.pop("jobs", None)
    p["config"] = {"planner": anthropic_configured(), "transcription": bool(elevenlabs_key())}
    return p


def _media_item(project: dict, mid: str) -> dict:
    check_id(mid, "media")
    for m in project["media"]:
        if m["id"] == mid:
            return m
    raise HTTPException(status_code=404, detail="unknown media")


def _unapprove(p: dict) -> None:
    if p["plan"].get("status") == "approved":
        p["plan"]["status"] = "draft"
        p["plan"]["approved_at"] = None


def _require_idle(pid: str) -> None:
    if jobs.active_job(pid):
        raise HTTPException(status_code=409, detail="A job is running for this project. Wait or cancel it first.")


# ---------------------------------------------------------------- auth / system

class LoginBody(BaseModel):
    token: str = Field(max_length=500)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/auth/status")
def auth_status(request: Request) -> dict:
    return {"required": auth.enabled(), "authenticated": auth.is_authenticated(request)}


@app.post("/api/auth/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    if not auth.enabled():
        return {"ok": True}
    if not auth.token_matches(body.token):
        raise HTTPException(status_code=401, detail="Invalid access token")
    response.set_cookie(auth.COOKIE, auth.session_value(), httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", max_age=30 * 24 * 3600)
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@app.get("/api/status")
def system_status() -> dict:
    ffmpeg_v, ffprobe_v = _tool_version("ffmpeg"), _tool_version("ffprobe")
    eng = engine.engine_status()
    usage = shutil.disk_usage(settings.workspace_dir)
    return {
        "services": [
            {"key": "ffmpeg", "name": "FFmpeg", "state": "ready" if ffmpeg_v else "missing",
             "detail": ffmpeg_v or "Not found on PATH", "required": True},
            {"key": "ffprobe", "name": "ffprobe", "state": "ready" if ffprobe_v else "missing",
             "detail": ffprobe_v or "Not found on PATH", "required": True},
            {"key": "engine", "name": "Video Engine", "state": "ready" if eng["ok"] else "error",
             "detail": "video-use helpers: " + ", ".join(eng["helpers"]) if eng["ok"]
             else "; ".join(eng["missing"] + eng["errors"]), "required": True},
            {"key": "planner", "name": "AI Edit Planner", "state": "ready" if anthropic_configured() else "not_configured",
             "detail": f"Claude · {settings.planner_model}" if anthropic_configured()
             else "Set ANTHROPIC_API_KEY to enable Generate Edit Plan", "required": True},
            {"key": "transcription", "name": "Transcription", "state": "ready" if elevenlabs_key() else "not_configured",
             "detail": "ElevenLabs Scribe (video-use transcribe.py)" if elevenlabs_key()
             else "Optional. Set ELEVENLABS_API_KEY to analyze speech", "required": False},
            {"key": "access", "name": "Access Protection", "state": "ready" if auth.enabled() else "not_configured",
             "detail": "Access token required" if auth.enabled()
             else "Open. Set CLOUD_VIDEO_ACCESS_TOKEN before exposing publicly", "required": False},
        ],
        "storage": {"free_bytes": usage.free, "total_bytes": usage.total,
                    "max_upload_bytes": settings.max_upload_bytes, "chunk_bytes": settings.chunk_bytes},
        "formats": [".mp4", ".mov"],
    }


@app.get("/api/presets")
def presets() -> list[dict]:
    return public_presets()


# ---------------------------------------------------------------- projects

class NewProject(BaseModel):
    name: str = Field(default="Untitled Project", max_length=200)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    prompt: str | None = Field(default=None, max_length=20000)
    preset: str | None = Field(default=None, max_length=40)
    target_duration: float | None = Field(default=None, ge=0, le=3600)


@app.get("/api/projects")
def list_projects() -> list[dict]:
    return store.list_projects()


@app.post("/api/projects")
def create_project(body: NewProject) -> dict:
    return _serialize(store.create(body.name))


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    return _serialize(store.load(pid))


@app.patch("/api/projects/{pid}")
def patch_project(pid: str, body: ProjectPatch) -> dict:
    fields = body.model_dump(exclude_unset=True)

    def fn(p: dict) -> None:
        if "name" in fields:
            p["name"] = clean_text(fields["name"], 120) or p["name"]
        if "prompt" in fields:
            p["prompt"] = clean_text(fields["prompt"] or "", 20000, multiline=True)
        if "preset" in fields:
            preset = fields["preset"] or None
            if preset is not None and preset not in PRESETS:
                raise HTTPException(status_code=400, detail="unknown preset")
            p["preset"] = preset
            if preset:
                p["render_settings"].update(PRESETS[preset]["render_defaults"])
                p["target_duration"] = p.get("target_duration") or PRESETS[preset]["target_duration"]
        if "target_duration" in fields:
            td = fields["target_duration"]
            p["target_duration"] = round(td) if td else None

    return _serialize(store.update(pid, fn))


@app.delete("/api/projects/{pid}")
def delete_project(pid: str) -> dict:
    _require_idle(pid)
    store.delete(pid)
    return {"ok": True}


# ---------------------------------------------------------------- uploads

class UploadStart(BaseModel):
    filename: str = Field(max_length=500)
    size: int = Field(gt=0)


@app.post("/api/projects/{pid}/uploads")
def upload_start(pid: str, body: UploadStart) -> dict:
    return uploads.start(pid, body.filename, body.size)


@app.get("/api/projects/{pid}/uploads/{uid}")
def upload_status(pid: str, uid: str) -> dict:
    check_id(pid, "project")
    return uploads.status(pid, uid)


@app.put("/api/projects/{pid}/uploads/{uid}")
async def upload_chunk(pid: str, uid: str, request: Request, offset: int = 0) -> dict:
    check_id(pid, "project")
    return await uploads.write_chunk(pid, uid, offset, request)


@app.post("/api/projects/{pid}/uploads/{uid}/complete")
def upload_complete(pid: str, uid: str) -> dict:
    check_id(pid, "project")
    uploads.complete(pid, uid)
    return _serialize(store.load(pid))


@app.delete("/api/projects/{pid}/uploads/{uid}")
def upload_cancel(pid: str, uid: str) -> dict:
    check_id(pid, "project")
    uploads.cancel(pid, uid)
    return {"ok": True}


# ---------------------------------------------------------------- media

class MediaPatch(BaseModel):
    display_name: str = Field(max_length=200)


class MediaOrder(BaseModel):
    ids: list[str] = Field(max_length=1000)


@app.patch("/api/projects/{pid}/media/{mid}")
def rename_media(pid: str, mid: str, body: MediaPatch) -> dict:
    def fn(p: dict) -> None:
        item = _media_item(p, mid)
        item["display_name"] = clean_text(body.display_name, 120) or item["display_name"]
    return _serialize(store.update(pid, fn))


@app.put("/api/projects/{pid}/media/order")
def reorder_media(pid: str, body: MediaOrder) -> dict:
    def fn(p: dict) -> None:
        current = {m["id"]: m for m in p["media"]}
        if sorted(body.ids) != sorted(current):
            raise HTTPException(status_code=400, detail="order must list every media id exactly once")
        p["media"] = [current[i] for i in body.ids]
    return _serialize(store.update(pid, fn))


@app.delete("/api/projects/{pid}/media/{mid}")
def remove_media(pid: str, mid: str) -> dict:
    _require_idle(pid)
    removed: dict[str, Any] = {}

    def fn(p: dict) -> None:
        item = _media_item(p, mid)
        p["media"] = [m for m in p["media"] if m["id"] != mid]
        p["analysis"].get("clips", {}).pop(mid, None)
        before = len(p["plan"].get("segments", []))
        p["plan"]["segments"] = [s for s in p["plan"].get("segments", []) if s["media_id"] != mid]
        if len(p["plan"]["segments"]) != before:
            _unapprove(p)
        removed.update(item)

    project = store.update(pid, fn)
    # Remove the project's stored copy (the user's own original elsewhere is untouched).
    input_file = safe_join(store.project_subdir(pid, "input"), removed["file"])
    input_file.unlink(missing_ok=True)
    assets = store.project_subdir(pid, "assets")
    for name in (removed.get("thumbnail"), f"filmstrip_{mid}.png"):
        if name:
            safe_join(assets, name).unlink(missing_ok=True)
    shutil.rmtree(safe_join(store.project_subdir(pid, "intermediate"), "analysis", mid), ignore_errors=True)
    return _serialize(project)


def _video_response(path: Path, download_name: str | None, original_ext: str) -> FileResponse:
    if download_name:
        mime = "video/quicktime" if original_ext == ".mov" else "video/mp4"
        return FileResponse(path, media_type=mime, filename=download_name, content_disposition_type="attachment")
    # Inline playback: H.264/HEVC in a .mov container generally plays when served as mp4.
    return FileResponse(path, media_type="video/mp4", content_disposition_type="inline")


@app.get("/api/projects/{pid}/media/{mid}/file")
def media_file(pid: str, mid: str, download: int = 0):
    item = _media_item(store.load(pid), mid)
    path = safe_join(store.project_subdir(pid, "input"), item["file"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file missing")
    return _video_response(path, item["file"] if download else None, path.suffix.lower())


@app.get("/api/projects/{pid}/media/{mid}/thumbnail")
def media_thumbnail(pid: str, mid: str):
    item = _media_item(store.load(pid), mid)
    if not item.get("thumbnail"):
        raise HTTPException(status_code=404, detail="no thumbnail")
    return FileResponse(safe_join(store.project_subdir(pid, "assets"), item["thumbnail"]), media_type="image/jpeg")


@app.get("/api/projects/{pid}/media/{mid}/filmstrip")
def media_filmstrip(pid: str, mid: str):
    _media_item(store.load(pid), mid)
    path = safe_join(store.project_subdir(pid, "assets"), f"filmstrip_{mid}.png")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no filmstrip")
    return FileResponse(path, media_type="image/png")


# ---------------------------------------------------------------- analysis & planning

@app.post("/api/projects/{pid}/analyze")
def start_analysis(pid: str) -> dict:
    project = store.load(pid)
    if not project["media"]:
        raise HTTPException(status_code=400, detail="Add media first.")
    jobs.submit(pid, "analyze", engine.ANALYSIS_STAGES, lambda ctx: engine.analyze(ctx, pid))
    return _serialize(store.load(pid))


@app.post("/api/projects/{pid}/plan/generate")
def generate_plan(pid: str) -> dict:
    project = store.load(pid)
    if not project["media"]:
        raise HTTPException(status_code=400, detail="Add media first.")
    jobs.submit(pid, "plan", planner.PLAN_STAGES, lambda ctx: planner.plan(ctx, pid))
    return _serialize(store.load(pid))


class SegmentIn(BaseModel):
    id: str | None = Field(default=None, max_length=40)
    media_id: str = Field(max_length=40)
    source_in: float = Field(ge=0)
    source_out: float = Field(ge=0)
    label: str = Field(default="", max_length=200)
    transition: str = Field(default="cut", max_length=20)
    transition_duration: float = Field(default=1.0, ge=0, le=10)
    notes: str = Field(default="", max_length=2000)


class PlanIn(BaseModel):
    segments: list[SegmentIn] = Field(max_length=200)
    title: str | None = Field(default=None, max_length=200)
    fade_in: bool = False
    fade_out: bool = False
    fade_duration: float = Field(default=1.0, ge=0.2, le=5)


@app.put("/api/projects/{pid}/plan")
def save_plan(pid: str, body: PlanIn) -> dict:
    _require_idle(pid)

    def fn(p: dict) -> None:
        durations = {m["id"]: float(m["meta"].get("duration") or 0) for m in p["media"]}
        raw = [s.model_dump() for s in body.segments]
        segs = planner.normalize_segments(raw, durations)
        if len(segs) != len(raw):
            raise HTTPException(status_code=400, detail="Each segment needs a valid clip and an out point at least 0.5s after its in point, inside the clip.")
        plan = p["plan"]
        plan.update(segments=segs, fade_in=body.fade_in, fade_out=body.fade_out,
                    fade_duration=round(body.fade_duration, 2), updated_at=store.now())
        if body.title is not None:
            plan["title"] = clean_text(body.title, 120)
        plan.setdefault("source", "manual")
        if plan.get("status") in (None, "none") and segs:
            plan["status"] = "draft"
        _unapprove(p)  # any edit requires re-approval

    return _serialize(store.update(pid, fn))


@app.post("/api/projects/{pid}/plan/approve")
def approve_plan(pid: str) -> dict:
    def fn(p: dict) -> None:
        if not p["plan"].get("segments"):
            raise HTTPException(status_code=400, detail="The plan has no segments.")
        ids = {m["id"] for m in p["media"]}
        if any(s["media_id"] not in ids for s in p["plan"]["segments"]):
            raise HTTPException(status_code=400, detail="The plan references removed media.")
        p["plan"]["status"] = "approved"
        p["plan"]["approved_at"] = store.now()
    return _serialize(store.update(pid, fn))


@app.post("/api/projects/{pid}/plan/revise")
def revise_plan(pid: str) -> dict:
    return _serialize(store.update(pid, _unapprove))


# ---------------------------------------------------------------- render

RENDER_CHOICES = {
    "resolution": {"original", "1080p", "4k"},
    "aspect": {"source", "16:9", "9:16", "1:1"},
    "fps": {"source", "24", "25", "30", "60"},
    "quality": {"preview", "high", "maximum"},
    "grade": {"none", "subtle", "neutral_punch", "warm_cinematic", "auto"},
    "fit": {"crop", "letterbox"},
    "audio": {"keep", "mute"},
}


@app.put("/api/projects/{pid}/render-settings")
def save_render_settings(pid: str, body: dict) -> dict:
    clean: dict[str, Any] = {}
    for key, value in body.items():
        if key in RENDER_CHOICES:
            if str(value) not in RENDER_CHOICES[key]:
                raise HTTPException(status_code=400, detail=f"invalid {key}")
            clean[key] = str(value)
        elif key in ("loudnorm", "burn_labels"):
            clean[key] = bool(value)
    return _serialize(store.update(pid, lambda p: p["render_settings"].update(clean)))


@app.post("/api/projects/{pid}/render")
def start_render(pid: str) -> dict:
    project = store.load(pid)
    if project["plan"].get("status") != "approved":
        raise HTTPException(status_code=400, detail="Approve the edit plan before rendering.")
    jobs.submit(pid, "render", engine.RENDER_STAGES, lambda ctx: engine.render(ctx, pid))
    return _serialize(store.load(pid))


@app.post("/api/projects/{pid}/jobs/cancel")
def cancel_job(pid: str) -> dict:
    check_id(pid, "project")
    return {"cancelled": jobs.cancel(pid)}


def _output(project: dict, oid: str) -> dict:
    for o in project["outputs"]:
        if o["id"] == oid:
            return o
    raise HTTPException(status_code=404, detail="unknown output")


@app.get("/api/projects/{pid}/outputs/{oid}/file")
def output_file(pid: str, oid: str, download: int = 0):
    project = store.load(pid)
    o = _output(project, oid)
    path = safe_join(store.project_subdir(pid, "output"), o["file"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file missing")
    name = None
    if download:
        slug = "".join(c if c.isalnum() else "-" for c in project["name"]).strip("-").lower()[:60] or "cloud-video"
        name = f"{slug}-{o['file']}"
    return _video_response(path, name, ".mp4")


@app.get("/api/projects/{pid}/outputs/{oid}/thumbnail")
def output_thumbnail(pid: str, oid: str):
    o = _output(store.load(pid), oid)
    path = safe_join(store.project_subdir(pid, "assets"), o["thumbnail"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no thumbnail")
    return FileResponse(path, media_type="image/jpeg")


@app.exception_handler(404)
async def not_found(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": getattr(exc, "detail", "not found")}, status_code=404)
    page = WEB_OUT_DIR / "404.html"
    if page.is_file():
        return FileResponse(page, status_code=404, media_type="text/html")
    return JSONResponse({"detail": "not found"}, status_code=404)


# ---------------------------------------------------------------- frontend

if WEB_OUT_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_OUT_DIR, html=True), name="web")
else:
    @app.get("/")
    def no_frontend() -> JSONResponse:
        return JSONResponse({"detail": "Frontend not built. Run: cd studio/web && npm ci && npm run build"},
                            status_code=503)
