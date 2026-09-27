"use client";

import { api } from "@/lib/api";
import { bytes, relativeDate, resolution, timecode } from "@/lib/format";
import type { Project, Selection } from "@/lib/types";
import { IconDownload, IconEdit, IconExternal, IconFilm } from "./Icons";
import { useToast } from "./Toasts";

interface Props {
  project: Project;
  onProject: (p: Project) => void;
  selection: Selection;
  onSelect: (s: Selection) => void;
  busy: boolean;
}

export function OutputPanel({ project, onProject, selection, onSelect, busy }: Props) {
  const toast = useToast();
  const outputs = project.outputs;
  const current = outputs.find((o) => selection?.kind === "output" && selection.id === o.id) ?? outputs[0];

  if (!current) {
    return (
      <div className="empty-state" style={{ border: "1px solid var(--line)", borderRadius: 12 }}>
        <IconFilm size={20} />
        <h3>No renders yet</h3>
        <p>Rendered versions appear here as version-001.mp4, version-002.mp4, … Earlier versions are always kept.</p>
      </div>
    );
  }

  const newVersion = async () => {
    try {
      if (project.plan.status === "approved") onProject(await api.revisePlan(project.id));
      document.getElementById("plan")?.scrollIntoView({ behavior: "smooth" });
      toast("Plan unlocked. Adjust it, approve, and render the next version.");
    } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <div>
      <div className="output-hero fade-in" key={current.id}>
        <video src={current.file_url} controls preload="metadata" poster={current.thumbnail_url} playsInline />
        <div className="output-info">
          <div className="kv"><span className="stat-k">File</span><span className="mono">{current.file}</span></div>
          <div className="kv"><span className="stat-k">Resolution</span><span className="mono">{resolution(current.width, current.height)}</span></div>
          <div className="kv"><span className="stat-k">Duration</span><span className="mono">{timecode(current.duration, true)}</span></div>
          <div className="kv"><span className="stat-k">Size</span><span className="mono">{bytes(current.size)}</span></div>
          <div className="output-actions">
            <a className="btn primary" href={current.download_url} download><IconDownload /> DOWNLOAD</a>
            <a className="btn" href={current.file_url} target="_blank" rel="noopener"><IconExternal /> OPEN OUTPUT</a>
            <button className="btn" onClick={newVersion} disabled={busy}><IconEdit /> CREATE NEW VERSION</button>
          </div>
        </div>
      </div>

      {outputs.length > 1 && (
        <div className="versions">
          {outputs.map((o) => (
            <div key={o.id} className={`version-row ${o.id === current.id ? "selected" : ""}`} onClick={() => onSelect({ kind: "output", id: o.id })}>
              <img src={o.thumbnail_url} alt="" loading="lazy" />
              <div style={{ minWidth: 0 }}>
                <div className="mono" style={{ fontSize: 12.5 }}>{o.file}</div>
                <div className="media-meta">
                  <span>{resolution(o.width, o.height)}</span><span>{timecode(o.duration)}</span>
                  <span>{o.fps_label} fps</span><span>{o.settings.quality}</span><span>{bytes(o.size)}</span>
                </div>
              </div>
              <span className="hint">{relativeDate(o.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
