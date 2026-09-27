"""AI edit planning with Claude.

In video-use, the reasoning step ("LLM Reasons → EDL") is done by the coding
agent reading SKILL.md. Here the web app performs that step itself by calling
the Claude API with the same inputs video-use would use: per-clip metadata,
scene cuts, keyframes (the "on-demand visuals" layer) and, when available,
the packed transcript (`takes_packed.md`). The output is a *proposed* plan,
stored as a draft. Nothing is rendered until the user approves it
(video-use Hard Rule 11: strategy confirmation before execution).

The user's prompt is only ever placed in the API request body. It never
reaches a shell or an ffmpeg argument.
"""

from __future__ import annotations

import base64
import json

from . import engine, store
from .config import anthropic_configured, settings
from .jobs import ConfigurationRequired, JobContext
from .presets import PRESETS
from .security import clean_text, new_id
from .timing import MIN_SEGMENT_S, TRANSITIONS

PLAN_STAGES = ["Preparing media", "Analyzing clips", "Generating edit plan", "Validating plan"]
MAX_IMAGES = 60

SYSTEM_PROMPT = """You are the editor inside CLOUD VIDEO, a private video editing workspace built on \
the open-source video-use engine. You propose an edit plan (a sequence of source ranges) from the \
user's footage and brief. The user reviews and approves the plan before anything is rendered.

You cannot watch the video. You read it through: clip metadata, scene-change timestamps, keyframe \
stills (labelled with clip and timestamp), and a word-level transcript summary when the footage \
has speech.

Rules:
- Every segment must reference a clip alias exactly as given (e.g. "clip_01") and use times inside \
that clip's duration. source_out must be greater than source_in.
- A segment should normally lie within one continuous shot. Avoid crossing a scene-change timestamp \
unless you intend to include the cut.
- If there is speech, never cut inside a word; pad cut edges by 50–200 ms. Prefer silences.
- transition describes how a segment ENTERS: "cut", "dissolve" (overlaps the previous shot by \
transition_duration seconds), or "dip_to_black". The first segment's transition is ignored; use \
fade_in / fade_out for the opening and closing.
- Aim for the requested target duration. Dissolves shorten the total by their duration.
- Labels are short (a room or beat name). Notes explain the choice in one sentence.
- In "summary", describe the strategy in 3–6 plain-English sentences, as you would before asking \
for approval. Put any caveats (e.g. footage too short for the target) in "warnings"."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "fade_in": {"type": "boolean"},
        "fade_out": {"type": "boolean"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clip": {"type": "string"},
                    "source_in": {"type": "number"},
                    "source_out": {"type": "number"},
                    "label": {"type": "string"},
                    "transition": {"type": "string", "enum": list(TRANSITIONS)},
                    "transition_duration": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": ["clip", "source_in", "source_out", "label", "transition",
                             "transition_duration", "notes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "summary", "warnings", "fade_in", "fade_out", "segments"],
    "additionalProperties": False,
}


def _b64(path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode("ascii")


def build_request_content(pid: str, project: dict) -> tuple[list[dict], dict[str, str]]:
    """User-turn content blocks (text + keyframe images) and the alias → media id map."""
    items = [m for m in project["media"] if m.get("status") == "ready"]
    analysis = project["analysis"].get("clips", {})
    aliases = {f"clip_{i + 1:02d}": m["id"] for i, m in enumerate(items)}
    rev = {v: k for k, v in aliases.items()}

    preset = PRESETS.get(project.get("preset") or "")
    target = project.get("target_duration")
    lines = ["# Brief", project.get("prompt") or "(no written instructions)", ""]
    if preset:
        lines += [f"# Preset: {preset['name']}", preset["guidance"], "", preset["planner_notes"], ""]
    lines += [f"# Target duration: {target} seconds" if target else "# Target duration: editor's judgement", ""]
    lines += ["# Clips (in the user's media order)"]
    for m in items:
        meta, a = m["meta"], analysis.get(m["id"], {})
        scenes = ", ".join(f"{t:.2f}" for t in a.get("scenes", [])[:40]) or "none detected"
        lines.append(
            f"- {rev[m['id']]}: name “{m['display_name']}”, duration {meta.get('duration') or 0:.2f}s, "
            f"{meta.get('width')}×{meta.get('height')} @ {meta.get('fps_label')} fps, "
            f"audio: {'yes' if meta.get('audio_streams') else 'no'}; scene changes at: {scenes}"
        )
    packed = engine.packed_transcript(pid)
    if packed:
        lines += ["", "# Transcript (video-use takes_packed.md; source names are file stems)", packed]
        stems = {m["file"].rsplit(".", 1)[0]: rev[m["id"]] for m in items}
        lines += ["", "File stem → clip alias: " + json.dumps(stems)]

    content: list[dict] = [{"type": "text", "text": "\n".join(lines)}]

    per_clip = max(2, MAX_IMAGES // max(1, len(items)))
    frames_root = store.project_subdir(pid, "intermediate") / "analysis"
    for m in items:
        kfs = analysis.get(m["id"], {}).get("keyframes", [])
        if len(kfs) > per_clip:
            step = len(kfs) / per_clip
            kfs = [kfs[int(i * step)] for i in range(per_clip)]
        for kf in kfs:
            path = frames_root / m["id"] / kf["file"]
            if path.is_file():
                content.append({"type": "text", "text": f"{rev[m['id']]} @ {kf['t']:.2f}s"})
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": _b64(path)}})
    content.append({"type": "text", "text": "Propose the edit plan."})
    return content, aliases


def _call_claude(content: list[dict]) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    try:
        # Streaming avoids HTTP timeouts on long, image-heavy requests.
        # Server-side refusal fallback ("default" mode) is enabled so a declined
        # request is retried on Anthropic's recommended fallback model.
        with client.beta.messages.stream(
            model=settings.planner_model,
            max_tokens=32000,
            betas=["server-side-fallback-2026-07-01"],
            thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            extra_body={"fallbacks": "default"},
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise ConfigurationRequired("ANTHROPIC_API_KEY was rejected (401). Check the key in studio/.env.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise ConfigurationRequired(f"The API key lacks permission for {settings.planner_model}.") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError("Claude API rate limit reached. Try again in a minute.") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("Could not reach the Claude API (network).") from exc

    if message.stop_reason == "refusal":
        raise RuntimeError("The planner declined this request. Try rephrasing the instructions.")
    if message.stop_reason == "max_tokens":
        raise RuntimeError("The plan was cut off (too long). Try a shorter target duration.")
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("The planner returned an unreadable plan.") from exc


def normalize_segments(raw: list[dict], durations: dict[str, float], id_map: dict[str, str] | None = None) -> list[dict]:
    """Validate/clamp segments from the AI or the browser into the stored shape."""
    segments = []
    for s in raw[:200]:
        ref = s.get("clip") if id_map is not None else s.get("media_id")
        mid = id_map.get(ref) if id_map is not None else ref
        if not isinstance(mid, str) or mid not in durations:
            continue
        dur = durations[mid]
        try:
            a = max(0.0, float(s.get("source_in", 0)))
            b = min(dur, float(s.get("source_out", 0)))
        except (TypeError, ValueError):
            continue
        if b - a < MIN_SEGMENT_S:
            continue
        transition = s.get("transition") if s.get("transition") in TRANSITIONS else "cut"
        try:
            tdur = float(s.get("transition_duration") or 1.0)
        except (TypeError, ValueError):
            tdur = 1.0
        segments.append({
            "id": s.get("id") if isinstance(s.get("id"), str) and s["id"].isalnum() and len(s["id"]) <= 40 else new_id("s"),
            "media_id": mid,
            "source_in": round(a, 3),
            "source_out": round(b, 3),
            "label": clean_text(s.get("label"), 80),
            "transition": transition,
            "transition_duration": round(min(3.0, max(0.2, tdur)), 2),
            "notes": clean_text(s.get("notes"), 600, multiline=True),
        })
    if segments:
        segments[0]["transition"] = "cut"
    return segments


def plan(ctx: JobContext, pid: str) -> dict:
    ctx.stage("Preparing media")
    project = store.load(pid)
    if not [m for m in project["media"] if m.get("status") == "ready"]:
        raise RuntimeError("Add at least one clip first.")
    if not anthropic_configured():
        raise ConfigurationRequired(
            "AI edit planning requires ANTHROPIC_API_KEY. Add it to studio/.env and restart the server. "
            "You can still build the plan manually with “Add segment”.")

    ctx.stage("Analyzing clips")
    if project["analysis"].get("status") != "done":
        engine.analyze(ctx, pid)  # runs the analysis phase inside this job
        project = store.load(pid)
        ctx.stage("Analyzing clips")

    ctx.stage("Generating edit plan", f"Claude · {settings.planner_model}")
    content, aliases = build_request_content(pid, project)
    result = _call_claude(content)

    ctx.stage("Validating plan")
    durations = {m["id"]: float(m["meta"].get("duration") or 0) for m in project["media"]}
    segments = normalize_segments(result.get("segments", []), durations, id_map=aliases)
    if not segments:
        raise RuntimeError("The planner returned no usable segments.")
    warnings = [clean_text(w, 300) for w in result.get("warnings", [])][:10]
    dropped = len(result.get("segments", [])) - len(segments)
    if dropped:
        warnings.append(f"{dropped} proposed segment(s) referenced invalid clips or times and were dropped.")

    new_plan = {
        "status": "draft",
        "source": "ai",
        "model": settings.planner_model,
        "title": clean_text(result.get("title"), 120),
        "summary": clean_text(result.get("summary"), 3000, multiline=True),
        "warnings": warnings,
        "fade_in": bool(result.get("fade_in")),
        "fade_out": bool(result.get("fade_out")),
        "fade_duration": 1.0,
        "segments": segments,
        "created_at": store.now(),
        "updated_at": store.now(),
        "approved_at": None,
    }
    store.update(pid, lambda p: p.update(plan=new_plan))
    return {"segments": len(segments)}
