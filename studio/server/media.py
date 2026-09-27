"""ffprobe metadata + thumbnails. Originals are only ever read, never modified."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

FFPROBE_TIMEOUT_S = 60
FFMPEG_THUMB_TIMEOUT_S = 120


class ProbeError(Exception):
    pass


def _rate(value: str | None) -> float | None:
    if not value or value in ("0/0", "N/A"):
        return None
    try:
        r = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return float(r) if r > 0 else None


def fps_label(fps: float | None) -> str:
    if not fps:
        return "—"
    for nominal in (23.976, 29.97, 59.94):
        if abs(fps - nominal) < 0.01:
            return f"{nominal:g}"
    return f"{fps:.2f}".rstrip("0").rstrip(".")


def probe(path: Path) -> dict:
    """Return normalized metadata for a video file, or raise ProbeError."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=FFPROBE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("ffprobe timed out") from exc
    if proc.returncode != 0:
        raise ProbeError("ffprobe could not read this file (is it a valid MP4/MOV?)")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProbeError("ffprobe returned invalid output") from exc

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    if video is None:
        raise ProbeError("file has no video stream")
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    fmt = data.get("format") or {}

    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    rotation = 0
    for sd in video.get("side_data_list") or []:
        if sd.get("rotation") is not None:
            try:
                rotation = int(round(float(sd["rotation"])))
            except (TypeError, ValueError):
                pass
    if rotation % 180 in (90, -90):
        width, height = height, width  # displayed dimensions

    fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
    duration = None
    for candidate in (fmt.get("duration"), video.get("duration")):
        try:
            duration = float(candidate)
            break
        except (TypeError, ValueError):
            continue

    return {
        "duration": round(duration, 3) if duration else None,
        "width": width,
        "height": height,
        "fps": round(fps, 5) if fps else None,
        "fps_label": fps_label(fps),
        "video_codec": video.get("codec_name"),
        "profile": video.get("profile"),
        "pix_fmt": video.get("pix_fmt"),
        "color_transfer": video.get("color_transfer"),
        "rotation": rotation,
        "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
        "audio_streams": len(audio),
        "audio_codec": audio[0].get("codec_name") if audio else None,
        "container": fmt.get("format_name"),
        # Browsers can usually play H.264/HEVC-in-MP4 directly; ProRes/DNx can't.
        "browser_playable": video.get("codec_name") in ("h264", "hevc", "av1", "vp9"),
    }


def make_thumbnail(src: Path, dest: Path, duration: float | None, width: int = 640) -> bool:
    """Grab a representative frame (~20% in) as a JPEG. Returns success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    t = max(0.0, (duration or 0) * 0.2)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{t:.3f}", "-i", str(src),
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-q:v", "4",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=FFMPEG_THUMB_TIMEOUT_S)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return dest.is_file() and dest.stat().st_size > 0
