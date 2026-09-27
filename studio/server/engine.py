"""Bridge between CLOUD VIDEO and the video-use engine.

video-use is an agent skill: SKILL.md holds the editing craft and helpers/
holds the ffmpeg/Python tools. This module plays the role of the agent's
hands. It invokes those helpers and imports their functions rather than
reimplementing them, and it keeps the two phases strictly separate:

  ANALYSIS  (analyze)  read-only inspection of the uploaded originals:
            scene detection, video-use timeline_view filmstrips, keyframes
            for the planner, and ElevenLabs Scribe transcription through
            video-use transcribe.py when a key is configured.

  RENDERING (render)   turns an *approved* plan into a video-use EDL
            (intermediate/edl.json) and renders it following video-use's
            hard rules: per-segment extract with grade and 30ms audio fades,
            lossless concat for hard cuts, and video-use two-pass loudnorm.
            Dissolves (which video-use's concat path cannot do) are assembled
            with a single xfade/acrossfade pass over the extracted segments.

Every external command is built as an argument list. User text (prompt,
labels, notes) never enters a command line; burned-in labels are passed to
ffmpeg through `textfile=`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import media, store
from .config import HELPERS_DIR, elevenlabs_key
from .jobs import JobContext
from .timing import compute_timeline

PYTHON = sys.executable
FONT_FILE = next((p for p in (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
) if os.path.isfile(p)), None)


# -------- video-use modules --------------------------------------------------

def _load_helper(name: str):
    """Import a video-use helper module from helpers/ (they import each other by bare name)."""
    if str(HELPERS_DIR) not in sys.path:
        sys.path.insert(0, str(HELPERS_DIR))
    spec = importlib.util.spec_from_file_location(f"video_use_{name}", HELPERS_DIR / f"{name}.py")
    if not spec or not spec.loader:
        raise ImportError(f"video-use helper {name}.py not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_vu_cache: dict[str, object] = {}


def vu(name: str):
    if name not in _vu_cache:
        _vu_cache[name] = _load_helper(name)
    return _vu_cache[name]


def engine_status() -> dict:
    """Checks for the Settings page: video-use helpers present and importable."""
    expected = ["render", "grade", "timeline_view", "transcribe", "transcribe_batch", "pack_transcripts"]
    missing = [h for h in expected if not (HELPERS_DIR / f"{h}.py").is_file()]
    errors = []
    for h in ("render", "grade", "timeline_view", "transcribe"):
        if h in missing:
            continue
        try:
            vu(h)
        except Exception as exc:  # report, don't crash
            errors.append(f"{h}: {exc}")
    return {"ok": not missing and not errors, "missing": missing, "errors": errors,
            "helpers": [h for h in expected if h not in missing]}


# -------- small ffmpeg helpers ------------------------------------------------

_TIME_RE = re.compile(r"out_time_us=(\d+)")


def _progress_parser(total_s: float, ctx: JobContext, base: float = 0.0, span: float = 1.0, msg: str | None = None):
    def on_line(line: str) -> None:
        m = _TIME_RE.match(line)
        if m and total_s > 0:
            frac = (int(m.group(1)) / 1e6) / total_s
            ctx.progress(base + span * min(1.0, frac), msg)
    return on_line


def _source_path(pid: str, item: dict) -> Path:
    return store.project_subdir(pid, "input") / item["file"]


def _filter_escape(value: str) -> str:
    """Escape a value for use inside an ffmpeg filter option."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


# ============================================================================
# ANALYSIS
# ============================================================================

ANALYSIS_STAGES = ["Preparing media", "Detecting scenes", "Building filmstrips", "Transcribing", "Finalizing"]
SCENE_THRESHOLD = 0.30
KEYFRAMES_PER_CLIP = 6


def _detect_scenes(ctx: JobContext, src: Path, duration: float, base: float, span: float) -> list[float]:
    """Scene-change timestamps via ffmpeg's scene score on a downscaled decode."""
    cuts: list[float] = []
    pts_re = re.compile(r"pts_time:([0-9.]+)")

    progress = _progress_parser(duration, ctx, base, span)

    def on_line(line: str) -> None:
        if "Parsed_showinfo" in line:
            m = pts_re.search(line)
            if m:
                cuts.append(round(float(m.group(1)), 3))
        else:
            progress(line)

    ctx.run([
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "info", "-progress", "pipe:1",
        "-i", str(src), "-an",
        "-vf", f"scale=320:-2,select='gt(scene,{SCENE_THRESHOLD})',showinfo",
        "-f", "null", "-",
    ], on_line=on_line)
    return sorted(set(cuts))


def _extract_keyframes(ctx: JobContext, src: Path, duration: float, scenes: list[float], dest: Path) -> list[dict]:
    """Small JPEG keyframes (evenly spaced + scene starts) for the AI planner."""
    dest.mkdir(parents=True, exist_ok=True)
    times = [duration * (i + 0.5) / KEYFRAMES_PER_CLIP for i in range(KEYFRAMES_PER_CLIP)]
    times += [min(duration - 0.05, s + 0.5) for s in scenes[:6]]
    times = sorted({round(t, 2) for t in times if 0 <= t < duration})
    frames = []
    for i, t in enumerate(times):
        out = dest / f"kf_{i:02d}.jpg"
        ctx.run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", str(src),
                 "-frames:v", "1", "-vf", "scale=512:-2", "-q:v", "5", str(out)])
        if out.is_file():
            frames.append({"t": t, "file": out.name})
    return frames


def analyze(ctx: JobContext, pid: str) -> dict:
    project = store.load(pid)
    items = [m for m in project["media"] if m.get("status") == "ready"]
    if not items:
        raise RuntimeError("Add at least one clip before analyzing.")

    edit_dir = store.project_subdir(pid, "intermediate")
    assets = store.project_subdir(pid, "assets")
    analysis_dir = edit_dir / "analysis"

    store.update(pid, lambda p: p["analysis"].update(status="running"))

    ctx.stage("Preparing media")
    clips: dict[str, dict] = {}
    for i, item in enumerate(items):
        src = _source_path(pid, item)
        if not src.is_file():
            raise RuntimeError(f"Source file for “{item['display_name']}” is missing.")
        # Re-probe: cheap, and guarantees the analysis matches the file on disk.
        meta = media.probe(src)
        clips[item["id"]] = {"duration": meta["duration"] or 0.0, "has_audio": meta["audio_streams"] > 0}
        ctx.progress((i + 1) / len(items), force=True)

    ctx.stage("Detecting scenes")
    for i, item in enumerate(items):
        c = clips[item["id"]]
        span = 1.0 / len(items)
        c["scenes"] = _detect_scenes(ctx, _source_path(pid, item), c["duration"], i * span, span)
        c["keyframes"] = _extract_keyframes(ctx, _source_path(pid, item), c["duration"], c["scenes"],
                                            analysis_dir / item["id"])

    ctx.stage("Building filmstrips", "video-use timeline_view")
    for i, item in enumerate(items):
        c = clips[item["id"]]
        out = assets / f"filmstrip_{item['id']}.png"
        # video-use's own visual drill-down tool: filmstrip + waveform composite.
        ctx.run([PYTHON, str(HELPERS_DIR / "timeline_view.py"), str(_source_path(pid, item)),
                 "0", f"{max(0.5, c['duration'] - 0.05):.3f}", "-o", str(out), "--n-frames", "10"],
                cwd=str(edit_dir))
        c["filmstrip"] = out.name if out.is_file() else None
        ctx.progress((i + 1) / len(items), force=True)

    ctx.stage("Transcribing")
    notes: list[str] = []
    key = elevenlabs_key()
    with_audio = [m for m in items if clips[m["id"]]["has_audio"]]
    if not with_audio:
        notes.append("No clip has an audio track. Analysis is visual only (typical for Blender renders).")
    elif not key:
        notes.append("Transcription not configured (ELEVENLABS_API_KEY). Speech was not analyzed; "
                     "the plan uses visual analysis only.")
    else:
        env = dict(os.environ, ELEVENLABS_API_KEY=key)
        for i, item in enumerate(with_audio):
            try:
                # video-use transcribe.py: cached per source, refuses silent tracks.
                ctx.run([PYTHON, str(HELPERS_DIR / "transcribe.py"), str(_source_path(pid, item)),
                         "--edit-dir", str(edit_dir)], env=env, cwd=str(edit_dir))
                clips[item["id"]]["transcript"] = True
            except RuntimeError as exc:
                if "silent" in str(exc):
                    clips[item["id"]]["transcript"] = False
                    notes.append(f"“{item['display_name']}”: audio track is silent, so it was skipped.")
                else:
                    raise
            ctx.progress((i + 1) / len(with_audio), force=True)
        if any(clips[m["id"]].get("transcript") for m in with_audio):
            ctx.run([PYTHON, str(HELPERS_DIR / "pack_transcripts.py"), "--edit-dir", str(edit_dir)],
                    cwd=str(edit_dir))

    ctx.stage("Finalizing")

    def save(p: dict) -> None:
        p["analysis"] = {"status": "done", "clips": clips, "notes": notes, "updated_at": store.now()}

    store.update(pid, save)
    return {"clips": len(clips), "notes": notes}


def packed_transcript(pid: str) -> str | None:
    path = store.project_subdir(pid, "intermediate") / "takes_packed.md"
    return path.read_text(encoding="utf-8")[:60_000] if path.is_file() else None


# ============================================================================
# RENDERING
# ============================================================================

RENDER_STAGES = ["Preparing media", "Analyzing clips", "Creating edit timeline",
                 "Rendering", "Encoding", "Finalizing"]

QUALITY = {
    #            preset,     crf, audio bitrate
    "preview": ("veryfast", 26, "128k"),
    "high": ("medium", 18, "192k"),
    "maximum": ("slow", 14, "320k"),
}
ASPECTS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}
SHORT_SIDE = {"1080p": 1080, "4k": 2160}
LABEL_FADE_S = 0.6


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def output_geometry(settings_: dict, first_meta: dict) -> tuple[int, int]:
    sw, sh = first_meta["width"] or 1920, first_meta["height"] or 1080
    ratio = ASPECTS.get(settings_["aspect"], sw / sh)
    short = SHORT_SIDE.get(settings_["resolution"], min(sw, sh))
    if ratio >= 1:
        return _even(short * ratio), _even(short)
    return _even(short), _even(short / ratio)


def build_edl(project: dict, pid: str) -> dict:
    """The approved plan as a video-use EDL (see SKILL.md › EDL format)."""
    by_id = {m["id"]: m for m in project["media"]}
    plan = project["plan"]
    sources: dict[str, str] = {}
    ranges = []
    timeline, total = compute_timeline(plan["segments"])
    for seg, t in zip(plan["segments"], timeline):
        item = by_id.get(seg["media_id"])
        if not item:
            raise RuntimeError(f"Segment “{seg.get('label') or seg['id']}” uses a clip that was removed.")
        name = Path(item["file"]).stem
        sources[name] = str(_source_path(pid, item))
        ranges.append({
            "source": name, "start": seg["source_in"], "end": seg["source_out"],
            "beat": seg.get("label", ""), "reason": seg.get("notes", ""),
            # CLOUD VIDEO extensions (ignored by video-use render.py):
            "transition": seg.get("transition", "cut"),
            "transition_duration": seg.get("transition_duration"),
            "output_in": t["output_in"], "output_out": t["output_out"],
        })
    grade = project["render_settings"].get("grade") or "none"
    return {
        "version": 1,
        "sources": sources,
        "ranges": ranges,
        "grade": "" if grade == "none" else grade,
        "overlays": [],
        "fade_in": plan.get("fade_in", False),
        "fade_out": plan.get("fade_out", False),
        "fade_duration": plan.get("fade_duration", 1.0),
        "total_duration_s": total,
    }


def _next_version(project: dict) -> int:
    return max((o["version"] for o in project.get("outputs", [])), default=0) + 1


def render(ctx: JobContext, pid: str) -> dict:
    render_mod = vu("render")
    grade_mod = vu("grade")

    # ---- Preparing media ------------------------------------------------------
    ctx.stage("Preparing media")
    project = store.load(pid)
    plan = project["plan"]
    if plan.get("status") != "approved":
        raise RuntimeError("The edit plan must be approved before rendering.")
    segments = plan["segments"]
    if not segments:
        raise RuntimeError("The edit plan has no segments.")
    rs = project["render_settings"]
    by_id = {m["id"]: m for m in project["media"]}
    edit_dir = store.project_subdir(pid, "intermediate")
    version = _next_version(project)
    work = edit_dir / f"render_v{version:03d}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # ---- Analyzing clips (probe every source the plan touches) ------------------
    ctx.stage("Analyzing clips")
    metas: dict[str, dict] = {}
    for i, seg in enumerate(segments):
        item = by_id.get(seg["media_id"])
        if not item:
            raise RuntimeError(f"Segment {i + 1:02d} uses a clip that was removed from the project.")
        if seg["media_id"] not in metas:
            src = _source_path(pid, item)
            if not src.is_file():
                raise RuntimeError(f"Source file for “{item['display_name']}” is missing.")
            meta = media.probe(src)
            meta["hdr"] = render_mod.is_hdr_source(src)
            metas[seg["media_id"]] = meta
        dur = metas[seg["media_id"]]["duration"] or 0
        if seg["source_out"] > dur + 0.05:
            raise RuntimeError(f"Segment {i + 1:02d} ends at {seg['source_out']:.2f}s but the clip is only {dur:.2f}s long.")
        ctx.progress((i + 1) / len(segments))

    # ---- Creating edit timeline (video-use EDL) ---------------------------------
    ctx.stage("Creating edit timeline")
    edl = build_edl(project, pid)
    (edit_dir / "edl.json").write_text(json.dumps(edl, indent=2))
    (work / "edl.json").write_text(json.dumps(edl, indent=2))

    first_meta = metas[segments[0]["media_id"]]
    width, height = output_geometry(rs, first_meta)
    if rs["fps"] == "source":
        out_rate = render_mod.probe_source_fps(_source_path(pid, by_id[segments[0]["media_id"]])) or "24"
    else:
        out_rate = render_mod.parse_fps(str(rs["fps"]))
    preset, crf, abr = QUALITY[rs["quality"]]
    keep_audio = rs["audio"] == "keep"
    has_dissolve = any(s["transition"] == "dissolve" for s in segments[1:])
    # Segments are re-encoded once more when dissolves are assembled, so extract
    # them near-losslessly in that case to avoid visible generational loss.
    seg_preset, seg_crf = ("veryfast", max(8, crf - 8)) if has_dissolve else (preset, crf)
    grade_filter = render_mod.resolve_grade_filter(edl["grade"]) if edl["grade"] else ""
    timeline, total = compute_timeline(segments)

    # ---- Rendering (per-segment extract — video-use Rule 2 & 3) -------------
    ctx.stage("Rendering", f"{len(segments)} segments · {width}×{height} · {out_rate} fps")
    seg_files: list[Path] = []
    real_audio = False
    for i, seg in enumerate(segments):
        item = by_id[seg["media_id"]]
        meta = metas[seg["media_id"]]
        src = _source_path(pid, item)
        start = float(seg["source_in"])
        dur = float(seg["source_out"]) - start

        # Fades to/from black: the plan's opening/closing, and dip-to-black joins.
        nxt = segments[i + 1] if i + 1 < len(segments) else None
        fade_in = fade_out = 0.0
        if i == 0 and plan.get("fade_in"):
            fade_in = float(plan.get("fade_duration") or 1.0)
        elif seg["transition"] == "dip_to_black":
            fade_in = float(seg.get("transition_duration") or 1.0) / 2
        if nxt is None and plan.get("fade_out"):
            fade_out = float(plan.get("fade_duration") or 1.0)
        elif nxt is not None and nxt["transition"] == "dip_to_black":
            fade_out = float(nxt.get("transition_duration") or 1.0) / 2
        fade_in, fade_out = min(fade_in, dur / 2), min(fade_out, dur / 2)

        vf: list[str] = []
        if meta["hdr"]:
            vf.append(render_mod.TONEMAP_CHAIN)  # video-use HDR → SDR
        if rs["fit"] == "letterbox":
            vf.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos")
            vf.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
        else:
            vf.append(f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos")
            vf.append(f"crop={width}:{height}")
        vf.append("setsar=1")
        if rs["grade"] == "auto":
            g, _ = grade_mod.auto_grade_for_clip(src, start=start, duration=dur, verbose=False)
            if g:
                vf.append(g)
        elif grade_filter:
            vf.append(grade_filter)
        vf.append(f"fps={out_rate}")
        if rs.get("burn_labels") and seg.get("label") and FONT_FILE:
            label_file = work / f"label_{i:02d}.txt"
            label_file.write_text(seg["label"], encoding="utf-8")
            a_in, a_out = 0.8, max(1.0, dur - 0.8 - fade_out)
            alpha = (f"if(lt(t,{a_in}),0,if(lt(t,{a_in + LABEL_FADE_S}),(t-{a_in})/{LABEL_FADE_S},"
                     f"if(lt(t,{a_out - LABEL_FADE_S}),1,if(lt(t,{a_out}),({a_out}-t)/{LABEL_FADE_S},0))))")
            vf.append(
                f"drawtext=fontfile='{_filter_escape(FONT_FILE)}':textfile='{_filter_escape(str(label_file))}'"
                f":fontsize=h*0.024:fontcolor=white@0.92:x=w*0.055:y=h-h*0.085-th"
                f":shadowcolor=black@0.35:shadowx=0:shadowy=1:alpha='{alpha}'"
            )
        if fade_in:
            vf.append(f"fade=t=in:st=0:d={fade_in:.3f}")
        if fade_out:
            vf.append(f"fade=t=out:st={dur - fade_out:.3f}:d={fade_out:.3f}")
        vf.append("format=yuv420p")

        use_src_audio = keep_audio and meta["audio_streams"] > 0
        real_audio = real_audio or use_src_audio
        # video-use Hard Rule 3: 30ms audio fades at every segment boundary.
        af = [f"afade=t=in:st=0:d={max(0.03, fade_in):.3f}",
              f"afade=t=out:st={max(0.0, dur - max(0.03, fade_out)):.3f}:d={max(0.03, fade_out):.3f}",
              "aresample=48000", "aformat=channel_layouts=stereo"]

        cmd = ["ffmpeg", "-y", "-hide_banner", "-nostdin", "-v", "error", "-progress", "pipe:1",
               "-ss", f"{start:.3f}", "-i", str(src)]
        if use_src_audio:
            fc = f"[0:v]{','.join(vf)}[v];[0:a:0]{','.join(af)}[a]"
        else:
            # Uniform stereo track on every segment keeps concat/xfade valid.
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            fc = f"[0:v]{','.join(vf)}[v];[1:a]anull[a]"
        out = work / f"seg_{i:02d}.mp4"
        cmd += ["-t", f"{dur:.3f}", "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", seg_preset, "-crf", str(seg_crf), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", abr, "-ar", "48000", "-ac", "2",
                "-video_track_timescale", "90000", "-movflags", "+faststart", str(out)]
        seg_label = seg.get("label") or item["display_name"]
        ctx.run(cmd, on_line=_progress_parser(dur, ctx, i / len(segments), 1 / len(segments),
                                              f"Segment {i + 1:02d}/{len(segments):02d} · {seg_label}"))
        seg_files.append(out)

    # ---- Encoding (assemble) ------------------------------------------------------
    ctx.stage("Encoding", "Assembling timeline")
    assembled = work / "assembled.mp4"
    if not has_dissolve:
        # video-use Hard Rule 2: lossless -c copy concat of the per-segment extracts.
        concat_list = work / "concat.txt"
        concat_list.write_text("".join(f"file '{p.name}'\n" for p in seg_files))
        ctx.run(["ffmpeg", "-y", "-hide_banner", "-nostdin", "-v", "error", "-f", "concat", "-safe", "0",
                 "-i", str(concat_list), "-c", "copy", "-movflags", "+faststart", str(assembled)],
                cwd=str(work))
    else:
        inputs: list[str] = []
        for p in seg_files:
            inputs += ["-i", str(p)]
        parts: list[str] = []
        v, a = "[0:v]", "[0:a]"
        acc = float(segments[0]["source_out"]) - float(segments[0]["source_in"])
        for i in range(1, len(segments)):
            nv, na = f"[v{i}]", f"[a{i}]"
            overlap = timeline[i]["overlap"]
            if overlap > 0:
                parts.append(f"{v}[{i}:v]xfade=transition=fade:duration={overlap:.3f}:offset={acc - overlap:.3f}{nv}")
                parts.append(f"{a}[{i}:a]acrossfade=d={overlap:.3f}:c1=tri:c2=tri{na}")
            else:
                parts.append(f"{v}{a}[{i}:v][{i}:a]concat=n=2:v=1:a=1{nv}{na}")
            v, a = nv, na
            acc = timeline[i]["output_out"]
        ctx.run(["ffmpeg", "-y", "-hide_banner", "-nostdin", "-v", "error", "-progress", "pipe:1", *inputs,
                 "-filter_complex", ";".join(parts), "-map", v, "-map", a,
                 "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
                 "-r", out_rate, "-c:a", "aac", "-b:a", abr, "-ar", "48000",
                 "-movflags", "+faststart", str(assembled)],
                on_line=_progress_parser(total, ctx))

    # ---- Finalizing ------------------------------------------------------------------
    ctx.stage("Finalizing")
    final_tmp = work / "final.mp4"
    if real_audio and rs.get("loudnorm", True):
        ctx.progress(None, "Loudness normalization (video-use, −14 LUFS)", force=True)
        render_mod.apply_loudnorm_two_pass(assembled, final_tmp, preview=rs["quality"] == "preview")
    elif not keep_audio:
        ctx.run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(assembled), "-map", "0:v", "-c", "copy",
                 "-movflags", "+faststart", str(final_tmp)])
    else:
        os.replace(assembled, final_tmp)

    out_dir = store.project_subdir(pid, "output")
    # Re-read in case another version landed meanwhile; never overwrite.
    version = max(version, _next_version(store.load(pid)))
    filename = f"version-{version:03d}.mp4"
    final_path = out_dir / filename
    while final_path.exists():
        version += 1
        filename = f"version-{version:03d}.mp4"
        final_path = out_dir / filename
    os.replace(final_tmp, final_path)

    info = media.probe(final_path)
    thumb = f"output_v{version:03d}.jpg"
    media.make_thumbnail(final_path, store.project_subdir(pid, "assets") / thumb, info["duration"])
    record = {
        "id": f"v{version:03d}",
        "version": version,
        "file": filename,
        "created_at": store.now(),
        "size": final_path.stat().st_size,
        "duration": info["duration"],
        "width": info["width"],
        "height": info["height"],
        "fps_label": info["fps_label"],
        "thumbnail": thumb,
        "settings": dict(rs),
        "plan_title": plan.get("title"),
        "segment_count": len(segments),
    }
    store.update(pid, lambda p: p["outputs"].append(record))
    # Per-segment extracts are large; the EDL copy stays for reference.
    for p in work.glob("*.mp4"):
        p.unlink(missing_ok=True)
    return {"output": record["id"], "file": filename}

