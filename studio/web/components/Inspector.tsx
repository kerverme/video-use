"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { bytes, fullDate, resolution, timecode } from "@/lib/format";
import { computeTimeline } from "@/lib/timing";
import type { Job, Project, Selection } from "@/lib/types";
import { IconAlert, IconCheck, IconX } from "./Icons";
import { useToast } from "./Toasts";

const JOB_TITLE: Record<string, string> = { analyze: "Analysis", plan: "Edit plan", render: "Render" };

function elapsed(job: Job, now: number) {
  const start = job.started_at ?? job.created_at;
  const end = job.finished_at ?? now / 1000;
  const s = Math.max(0, Math.round(end - start));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function JobStatus({ project, job }: { project: Project; job: Job | null }) {
  const toast = useToast();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!job) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [job]);

  const shown = job ?? project.last_job;
  if (!shown) return <div className="hint">No jobs yet. Analysis, planning and rendering run on the server; the page stays responsive.</div>;

  const running = !!job;
  const stageIdx = shown.stage ? shown.stages.indexOf(shown.stage) : -1;
  const statusChip = {
    queued: <span className="chip"><span className="spinner" /> Queued</span>,
    running: <span className="chip accent"><span className="spinner" /> Running · {elapsed(shown, now)}</span>,
    done: <span className="chip ok"><IconCheck size={12} /> Complete · {elapsed(shown, now)}</span>,
    error: <span className="chip danger"><IconAlert size={12} /> Failed</span>,
    cancelled: <span className="chip">Cancelled</span>,
    config_required: <span className="chip warn"><IconAlert size={12} /> Configuration Required</span>,
  }[shown.status];

  return (
    <div>
      <div className="status-line">
        <span style={{ fontWeight: 500 }}>{JOB_TITLE[shown.kind]}</span>
        <span style={{ marginLeft: "auto" }}>{statusChip}</span>
      </div>
      {running && (
        <div className={`progress ${shown.progress == null ? "indeterminate" : ""}`} style={{ marginTop: 12 }}>
          <i style={{ width: `${(shown.progress ?? 0) * 100}%` }} />
        </div>
      )}
      <ul className="stage-list">
        {shown.stages.map((st, i) => {
          const done = shown.status === "done" || (stageIdx >= 0 && i < stageIdx);
          const current = running && i === stageIdx;
          const failed = !running && shown.status !== "done" && i === stageIdx;
          return (
            <li key={st} className={done ? "done" : current ? "current" : ""}>
              <span className="stage-mark">
                {done ? <IconCheck size={12} /> : current ? <span className="spinner" /> : failed ? <IconX size={12} style={{ color: "var(--danger)" }} /> : "·"}
              </span>
              {st}…
              {current && shown.progress != null && <span className="mono muted" style={{ marginLeft: "auto" }}>{Math.round(shown.progress * 100)}%</span>}
            </li>
          );
        })}
      </ul>
      {shown.stage && stageIdx < 0 && running && <div className="job-msg">{shown.stage}</div>}
      {shown.message && running && <div className="job-msg">{shown.message}</div>}
      {shown.error && (
        <div className={`notice ${shown.status === "config_required" ? "warn" : "danger"}`} style={{ marginTop: 12 }}>
          <IconAlert />
          <div style={{ wordBreak: "break-word" }}>{shown.error}</div>
        </div>
      )}
      {running && (
        <button className="btn sm" style={{ marginTop: 14 }} onClick={async () => {
          try { await api.cancelJob(project.id); } catch (e) { toast((e as Error).message, "error"); }
        }}>Cancel</button>
      )}
    </div>
  );
}

export function Inspector({ project, selection, job }: { project: Project; selection: Selection; job: Job | null }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playErr, setPlayErr] = useState(false);

  const media = selection?.kind === "media" ? project.media.find((m) => m.id === selection.id) : undefined;
  const { segments: timed } = computeTimeline(project.plan.segments);
  const segment = selection?.kind === "segment" ? timed.find((s) => s.id === selection.id) : undefined;
  const segMedia = segment ? project.media.find((m) => m.id === segment.media_id) : undefined;
  const output = selection?.kind === "output" ? project.outputs.find((o) => o.id === selection.id) : !selection ? project.outputs[0] : undefined;
  const fallbackMedia = !media && !segment && !output ? project.media[0] : undefined;
  const clip = media ?? segMedia ?? fallbackMedia;

  const src = output ? output.file_url : clip?.file_url;
  const poster = output ? output.thumbnail_url : clip?.thumbnail_url ?? undefined;
  const range = segment ? `#t=${segment.source_in.toFixed(2)},${segment.source_out.toFixed(2)}` : "";

  useEffect(() => setPlayErr(false), [src]);

  // Keep segment playback inside its source range.
  const onTime = () => {
    const v = videoRef.current;
    if (v && segment && v.currentTime >= segment.source_out) v.pause();
  };

  const caption = output ? output.file : segment ? `Segment · ${segment.label || "Untitled"}` : clip ? clip.display_name : "";

  return (
    <aside className="inspector">
      <section className="insp-section">
        <h3 className="insp-title">Preview</h3>
        <div className="viewer">
          {src && !playErr ? (
            <video ref={videoRef} key={src + range} src={src + range} poster={poster} controls preload="metadata" playsInline
              onTimeUpdate={onTime} onError={() => setPlayErr(true)} />
          ) : poster ? (
            <img src={poster} alt="" />
          ) : (
            <div className="empty">Upload media or render a version to preview it here.</div>
          )}
        </div>
        {playErr && <div className="hint" style={{ marginTop: 8 }}>This browser can’t play {output ? "this file" : `${(clip?.meta.video_codec ?? "this").toUpperCase()} video`} (common for ProRes). The file is intact and renders normally.</div>}
        {caption && (
          <div className="viewer-caption">
            <span className="truncate">{caption}</span>
            {segment && <span className="mono">{timecode(segment.output_in)} → {timecode(segment.output_out)}</span>}
          </div>
        )}
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Current Selection</h3>
        {segment ? (
          <dl className="kv-table">
            <dt>Segment</dt><dd>{segment.label || "Untitled"}</dd>
            <dt>Source clip</dt><dd>{segMedia?.display_name ?? "Missing"}</dd>
            <dt>Source in</dt><dd>{segment.source_in.toFixed(2)}s</dd>
            <dt>Source out</dt><dd>{segment.source_out.toFixed(2)}s</dd>
            <dt>Output in</dt><dd>{timecode(segment.output_in, true)}</dd>
            <dt>Output out</dt><dd>{timecode(segment.output_out, true)}</dd>
            <dt>Transition</dt><dd>{segment.transition === "cut" ? "Cut" : `${segment.transition === "dissolve" ? "Dissolve" : "Dip to black"} ${segment.transition_duration}s`}</dd>
          </dl>
        ) : output ? (
          <dl className="kv-table">
            <dt>Version</dt><dd>{output.file}</dd>
            <dt>Rendered</dt><dd>{fullDate(output.created_at)}</dd>
            <dt>Segments</dt><dd>{output.segment_count}</dd>
            <dt>Quality</dt><dd>{output.settings.quality}</dd>
          </dl>
        ) : clip ? (
          <dl className="kv-table">
            <dt>Clip</dt><dd>{clip.display_name}</dd>
            <dt>File</dt><dd>{clip.file}</dd>
            <dt>Added</dt><dd>{fullDate(clip.added_at)}</dd>
            <dt>Scenes</dt><dd>{clip.scene_count == null ? "Not analyzed" : `${clip.scene_count + 1} shot${clip.scene_count === 0 ? "" : "s"} detected`}</dd>
          </dl>
        ) : <div className="hint">Nothing selected.</div>}
        {clip?.filmstrip_url && !output && <img className="filmstrip" src={clip.filmstrip_url} alt="video-use timeline view" />}
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Render Status</h3>
        <JobStatus project={project} job={job} />
      </section>

      <section className="insp-section" style={{ borderBottom: 0 }}>
        <h3 className="insp-title">Metadata</h3>
        {output ? (
          <dl className="kv-table">
            <dt>Resolution</dt><dd>{resolution(output.width, output.height)}</dd>
            <dt>Duration</dt><dd>{output.duration?.toFixed(2)}s</dd>
            <dt>Frame rate</dt><dd>{output.fps_label} fps</dd>
            <dt>Size</dt><dd>{bytes(output.size)}</dd>
            <dt>Codec</dt><dd>H.264 · AAC · MP4</dd>
          </dl>
        ) : clip ? (
          <dl className="kv-table">
            <dt>Duration</dt><dd>{clip.meta.duration?.toFixed(3)}s</dd>
            <dt>Resolution</dt><dd>{resolution(clip.meta.width, clip.meta.height)}</dd>
            <dt>Frame rate</dt><dd>{clip.meta.fps_label} fps</dd>
            <dt>Video codec</dt><dd>{clip.meta.video_codec ?? "—"}{clip.meta.pix_fmt ? ` · ${clip.meta.pix_fmt}` : ""}</dd>
            <dt>Color</dt><dd>{clip.meta.color_transfer ?? "—"}</dd>
            <dt>Audio</dt><dd>{clip.meta.audio_streams ? `${clip.meta.audio_codec} · ${clip.meta.audio_streams} track${clip.meta.audio_streams > 1 ? "s" : ""}` : "None"}</dd>
            <dt>File size</dt><dd>{bytes(clip.size)}</dd>
          </dl>
        ) : <div className="hint">—</div>}
      </section>
    </aside>
  );
}
