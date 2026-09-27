"""Edit-plan timing: output timeline positions for each segment.

A segment's `transition` describes how it *enters*:

  cut           back to back
  dissolve      overlaps the tail of the previous segment (output shortens)
  dip_to_black  previous segment fades out, this one fades in (no overlap)

The opening fade-in / closing fade-out are plan-level flags. The frontend
mirrors this logic (web/lib/timing.ts) for instant feedback; the server is
authoritative.
"""

from __future__ import annotations

TRANSITIONS = ("cut", "dissolve", "dip_to_black")
DEFAULT_TRANSITION_S = 1.0
MIN_SEGMENT_S = 0.5
MAX_TRANSITION_S = 3.0


def effective_transition(seg: dict, prev_duration: float | None) -> float:
    """Overlap (seconds) that this segment's incoming transition takes from the timeline."""
    if prev_duration is None or seg.get("transition") != "dissolve":
        return 0.0
    dur = float(seg.get("transition_duration") or DEFAULT_TRANSITION_S)
    this_dur = float(seg["source_out"]) - float(seg["source_in"])
    # A dissolve can never be longer than half of either neighbouring shot.
    return max(0.0, min(dur, MAX_TRANSITION_S, prev_duration / 2, this_dur / 2))


def compute_timeline(segments: list[dict]) -> tuple[list[dict], float]:
    """Return per-segment {output_in, output_out, overlap} and the total duration."""
    out: list[dict] = []
    cursor = 0.0
    prev_dur: float | None = None
    for seg in segments:
        dur = max(0.0, float(seg["source_out"]) - float(seg["source_in"]))
        overlap = effective_transition(seg, prev_dur)
        start = cursor - overlap
        end = start + dur
        out.append({"output_in": round(start, 3), "output_out": round(end, 3), "overlap": round(overlap, 3)})
        cursor = end
        prev_dur = dur
    return out, round(cursor, 3)
