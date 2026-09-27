"use client";

import { api } from "@/lib/api";
import { timecode } from "@/lib/format";
import type { Job, Project, RenderSettings } from "@/lib/types";
import { IconChevron, IconLock, IconRender } from "./Icons";
import { useToast } from "./Toasts";

type Opt<T extends string> = { value: T; label: string };

function Segmented<T extends string>({ value, options, onChange, disabled }: { value: T; options: Opt<T>[]; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <div className="segmented" role="radiogroup">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} className={value === o.value ? "on" : ""}
          disabled={disabled} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

const RES: Opt<RenderSettings["resolution"]>[] = [{ value: "original", label: "Original" }, { value: "1080p", label: "1080p" }, { value: "4k", label: "4K" }];
const ASPECT: Opt<RenderSettings["aspect"]>[] = [{ value: "source", label: "Source" }, { value: "16:9", label: "16:9" }, { value: "9:16", label: "9:16" }, { value: "1:1", label: "1:1" }];
const FPS: Opt<RenderSettings["fps"]>[] = [{ value: "source", label: "Source" }, { value: "24", label: "24" }, { value: "25", label: "25" }, { value: "30", label: "30" }, { value: "60", label: "60" }];
const QUALITY: Opt<RenderSettings["quality"]>[] = [{ value: "preview", label: "Preview" }, { value: "high", label: "High" }, { value: "maximum", label: "Maximum" }];

interface Props {
  project: Project;
  onProject: (p: Project) => void;
  job: Job | null;
}

export function RenderPanel({ project, onProject, job }: Props) {
  const toast = useToast();
  const rs = project.render_settings;
  const approved = project.plan.status === "approved";
  const disabled = !!job;

  const set = async (patch: Partial<RenderSettings>) => {
    onProject({ ...project, render_settings: { ...rs, ...patch } });
    try { onProject(await api.saveRenderSettings(project.id, patch)); } catch (e) { toast((e as Error).message, "error"); }
  };

  const start = async () => {
    try { onProject(await api.render(project.id)); } catch (e) { toast((e as Error).message, "error"); }
  };

  const nextVersion = (project.outputs[0]?.version ?? 0) + 1;

  return (
    <div>
      <div className="render-grid">
        <div className="field"><span className="field-label">Resolution</span>
          <Segmented value={rs.resolution} options={RES} onChange={(v) => set({ resolution: v })} disabled={disabled} /></div>
        <div className="field"><span className="field-label">Aspect ratio</span>
          <Segmented value={rs.aspect} options={ASPECT} onChange={(v) => set({ aspect: v })} disabled={disabled} /></div>
        <div className="field"><span className="field-label">Frame rate</span>
          <Segmented value={rs.fps} options={FPS} onChange={(v) => set({ fps: v })} disabled={disabled} /></div>
        <div className="field"><span className="field-label">Quality</span>
          <Segmented value={rs.quality} options={QUALITY} onChange={(v) => set({ quality: v })} disabled={disabled} /></div>
        <div className="field"><span className="field-label">Format</span>
          <div className="segmented"><button className="on" disabled>MP4 · H.264</button></div></div>
      </div>

      <details className="advanced">
        <summary><IconChevron size={12} className="icon chev" /> Advanced</summary>
        <div className="adv-grid">
          <div className="field"><span className="field-label">Color grade (video-use grade.py)</span>
            <select className="select" value={rs.grade} disabled={disabled} onChange={(e) => set({ grade: e.target.value as RenderSettings["grade"] })}>
              <option value="none">None (untouched)</option>
              <option value="subtle">Subtle cleanup</option>
              <option value="neutral_punch">Neutral punch</option>
              <option value="warm_cinematic">Warm cinematic</option>
              <option value="auto">Auto (per-segment analysis)</option>
            </select></div>
          <div className="field"><span className="field-label">Reframing when aspect changes</span>
            <Segmented value={rs.fit} options={[{ value: "crop", label: "Fill (crop)" }, { value: "letterbox", label: "Fit (letterbox)" }]}
              onChange={(v) => set({ fit: v })} disabled={disabled} /></div>
          <div className="field"><span className="field-label">Audio</span>
            <Segmented value={rs.audio} options={[{ value: "keep", label: "Keep source audio" }, { value: "mute", label: "No audio" }]}
              onChange={(v) => set({ audio: v })} disabled={disabled} /></div>
          <div className="field" style={{ gap: 12, paddingTop: 4 }}>
            <label className="toggle"><input type="checkbox" checked={rs.loudnorm} disabled={disabled} onChange={(e) => set({ loudnorm: e.target.checked })} />
              <span className="track" /> Loudness normalize (−14 LUFS)</label>
            <label className="toggle"><input type="checkbox" checked={rs.burn_labels} disabled={disabled} onChange={(e) => set({ burn_labels: e.target.checked })} />
              <span className="track" /> Minimal room labels from segment names</label>
          </div>
        </div>
      </details>

      <div className="render-cta">
        <button className="btn accent lg" onClick={start} disabled={!approved || disabled}>
          <IconRender /> RENDER VERSION {String(nextVersion).padStart(3, "0")}
        </button>
        {!approved ? (
          <span className="hint"><IconLock size={12} /> Approve the edit plan to enable rendering.</span>
        ) : (
          <span className="hint">
            {project.plan.segments.length} segments · {timecode(project.plan.total_duration)} · renders server-side. You can keep working.
          </span>
        )}
      </div>
    </div>
  );
}
