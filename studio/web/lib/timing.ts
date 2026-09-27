// Mirrors studio/server/timing.py so plan edits show updated timings instantly.
import type { Segment } from "./types";

const DEFAULT_TRANSITION_S = 1.0;
const MAX_TRANSITION_S = 3.0;

export function computeTimeline(segments: Segment[]): { segments: Segment[]; total: number } {
  let cursor = 0;
  let prevDur: number | null = null;
  const out = segments.map((seg) => {
    const dur = Math.max(0, seg.source_out - seg.source_in);
    let overlap = 0;
    if (prevDur !== null && seg.transition === "dissolve") {
      const want = seg.transition_duration || DEFAULT_TRANSITION_S;
      overlap = Math.max(0, Math.min(want, MAX_TRANSITION_S, prevDur / 2, dur / 2));
    }
    const start = cursor - overlap;
    const end = start + dur;
    cursor = end;
    prevDur = dur;
    return { ...seg, output_in: start, output_out: end, overlap };
  });
  return { segments: out, total: cursor };
}
