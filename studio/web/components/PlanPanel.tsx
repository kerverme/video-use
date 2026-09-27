"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { pad2, parseTime, timecode } from "@/lib/format";
import { computeTimeline } from "@/lib/timing";
import type { Job, Project, Segment, Selection, Transition } from "@/lib/types";
import { IconAlert, IconCheck, IconDown, IconEdit, IconGrip, IconLock, IconPlus, IconTrash, IconUp } from "./Icons";
import { useToast } from "./Toasts";

const TRANSITIONS: { value: Transition; label: string }[] = [
  { value: "cut", label: "Cut" },
  { value: "dissolve", label: "Dissolve" },
  { value: "dip_to_black", label: "Dip to black" },
];

interface Props {
  project: Project;
  onProject: (p: Project) => void;
  selection: Selection;
  onSelect: (s: Selection) => void;
  job: Job | null;
}

function TimeInput({ value, onCommit, disabled, label }: { value: number; onCommit: (v: number) => void; disabled?: boolean; label: string }) {
  const [text, setText] = useState(value.toFixed(2));
  useEffect(() => setText(value.toFixed(2)), [value]);
  return (
    <input className="input mono" aria-label={label} value={text} disabled={disabled}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        const v = parseTime(text);
        if (v === null) setText(value.toFixed(2));
        else onCommit(Math.round(v * 1000) / 1000);
      }}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
  );
}

export function PlanPanel({ project, onProject, selection, onSelect, job }: Props) {
  const toast = useToast();
  const plan = project.plan;
  const [segs, setSegs] = useState<Segment[]>(plan.segments);
  const [fades, setFades] = useState({ in: !!plan.fade_in, out: !!plan.fade_out, dur: plan.fade_duration ?? 1 });
  const dirty = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [drag, setDrag] = useState<{ id: string; target?: string; after?: boolean } | null>(null);
  const approved = plan.status === "approved";
  const locked = approved || !!job;
  const mediaById = useMemo(() => Object.fromEntries(project.media.map((m) => [m.id, m])), [project.media]);

  // Adopt server state unless the user has unsaved edits in flight.
  useEffect(() => {
    if (dirty.current) return;
    setSegs(plan.segments);
    setFades({ in: !!plan.fade_in, out: !!plan.fade_out, dur: plan.fade_duration ?? 1 });
  }, [plan]);

  const { segments: timed, total } = useMemo(() => computeTimeline(segs), [segs]);

  const persist = (next: Segment[], nextFades = fades) => {
    dirty.current = true;
    setSegs(next);
    setFades(nextFades);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      try {
        const p = await api.savePlan(project.id, {
          segments: next, title: plan.title, fade_in: nextFades.in, fade_out: nextFades.out, fade_duration: nextFades.dur,
        });
        dirty.current = false;
        onProject(p);
      } catch (e) {
        dirty.current = false;
        toast((e as Error).message, "error");
        setSegs(plan.segments);
      }
    }, 450);
  };

  const update = (id: string, fields: Partial<Segment>) =>
    persist(segs.map((s) => (s.id === id ? { ...s, ...fields } : s)));

  const addSegment = () => {
    const m = (selection?.kind === "media" && mediaById[selection.id]) || project.media[0];
    if (!m) return toast("Upload a clip first.", "error");
    const dur = m.meta.duration ?? 0;
    const seg: Segment = {
      id: `s${Date.now().toString(36)}`, media_id: m.id, source_in: 0, source_out: Math.min(dur, 6),
      label: m.display_name, transition: segs.length ? "dissolve" : "cut", transition_duration: 1, notes: "",
    };
    persist([...segs, seg]);
  };

  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= segs.length) return;
    const next = [...segs];
    [next[i], next[j]] = [next[j], next[i]];
    persist(next);
  };

  const onDrop = () => {
    if (!drag?.target || drag.target === drag.id) return setDrag(null);
    const moving = segs.find((s) => s.id === drag.id)!;
    const rest = segs.filter((s) => s.id !== drag.id);
    let at = rest.findIndex((s) => s.id === drag.target);
    if (drag.after) at += 1;
    rest.splice(at, 0, moving);
    setDrag(null);
    persist(rest);
  };

  const approve = async () => {
    clearTimeout(saveTimer.current);
    try {
      if (dirty.current) {
        await api.savePlan(project.id, { segments: segs, title: plan.title, fade_in: fades.in, fade_out: fades.out, fade_duration: fades.dur });
        dirty.current = false;
      }
      onProject(await api.approvePlan(project.id));
      document.getElementById("render")?.scrollIntoView({ behavior: "smooth" });
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const revise = async () => {
    try { onProject(await api.revisePlan(project.id)); } catch (e) { toast((e as Error).message, "error"); }
  };

  const planJob = job && (job.kind === "plan" || job.kind === "analyze") ? job : null;
  const last = project.last_job;
  const lastPlanIssue = !job && segs.length === 0 && last && last.kind === "plan" && (last.status === "config_required" || last.status === "error") ? last : null;

  return (
    <div>
      {planJob && (
        <div className="notice fade-in" style={{ marginBottom: 18 }}>
          <div className="spinner" style={{ marginTop: 3 }} />
          <div style={{ flex: 1 }}>
            <div className="notice-title">{planJob.kind === "plan" ? "Generating edit plan" : "Analyzing media"}</div>
            <div>{planJob.stage ?? "Queued"}{planJob.message ? ` · ${planJob.message}` : ""}</div>
          </div>
        </div>
      )}

      {lastPlanIssue?.status === "config_required" && (
        <div className="notice warn fade-in" style={{ marginBottom: 18 }}>
          <IconAlert />
          <div>
            <div className="notice-title">Configuration Required</div>
            <div>{lastPlanIssue.error}</div>
          </div>
        </div>
      )}
      {lastPlanIssue?.status === "error" && (
        <div className="notice danger fade-in" style={{ marginBottom: 18 }}>
          <IconAlert />
          <div>
            <div className="notice-title">Plan generation failed</div>
            <div>{lastPlanIssue.error}</div>
          </div>
        </div>
      )}

      {approved && (
        <div className="plan-approved fade-in">
          <IconLock /> <span style={{ flex: 1 }}>Plan approved. Ready to render.</span>
          <button className="btn sm" onClick={revise} disabled={!!job}><IconEdit size={13} /> Edit Plan</button>
        </div>
      )}

      {plan.summary && <p className="plan-summary">{plan.summary}</p>}
      {plan.warnings && plan.warnings.length > 0 && (
        <div className="notice warn" style={{ marginBottom: 18 }}>
          <IconAlert />
          <div>{plan.warnings.map((w, i) => <div key={i}>{w}</div>)}</div>
        </div>
      )}

      {segs.length > 0 ? (
        <>
          <div className="plan-stats">
            <div><div className="stat-v">{timecode(total)}</div><div className="stat-k">Output duration</div></div>
            <div><div className="stat-v">{pad2(segs.length)}</div><div className="stat-k">Segments</div></div>
            {project.target_duration ? <div><div className="stat-v">{timecode(project.target_duration)}</div><div className="stat-k">Target</div></div> : null}
            <div><div className="stat-v" style={{ fontSize: 13, paddingTop: 5 }}>{plan.source === "ai" ? `AI · ${plan.model}` : "Manual"}</div><div className="stat-k">Source</div></div>
          </div>

          <div className="timeline-bar" aria-hidden="true">
            {timed.map((s, i) => (
              <div key={s.id} style={{ flexGrow: Math.max(0.001, s.output_out! - s.output_in! - (s.overlap ?? 0)) }}
                className={selection?.kind === "segment" && selection.id === s.id ? "on" : ""}
                onClick={() => onSelect({ kind: "segment", id: s.id })} title={s.label}>
                {pad2(i + 1)} {s.label}
              </div>
            ))}
          </div>

          <div className="seg-list">
            {timed.map((s, i) => {
              const m = mediaById[s.media_id];
              const selected = selection?.kind === "segment" && selection.id === s.id;
              const dropCls = drag?.target === s.id && drag.id !== s.id ? (drag.after ? "drop-after" : "drop-before") : "";
              return (
                <div key={s.id} className={`seg ${selected ? "selected" : ""} ${drag?.id === s.id ? "dragging" : ""} ${dropCls}`}
                  onClick={() => onSelect({ kind: "segment", id: s.id })}
                  onDragOver={(e) => {
                    if (!drag) return;
                    e.preventDefault();
                    const r = e.currentTarget.getBoundingClientRect();
                    setDrag({ ...drag, target: s.id, after: e.clientY > r.top + r.height / 2 });
                  }}
                  onDrop={(e) => { if (drag) { e.preventDefault(); onDrop(); } }}>
                  <div className="handle" draggable={!locked} title={locked ? "" : "Drag to reorder"} style={{ paddingTop: 4, cursor: locked ? "default" : "grab" }}
                    onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", s.id); setDrag({ id: s.id }); }}
                    onDragEnd={() => setDrag(null)}>
                    {!locked && <IconGrip />}
                  </div>
                  <div className="seg-num">{pad2(i + 1)}</div>
                  <div style={{ minWidth: 0 }}>
                    <div className="seg-head">
                      {locked ? <span className="seg-label">{s.label || "Untitled"}</span> : (
                        <input className="input inline seg-label" value={s.label} maxLength={80} placeholder="Label"
                          onChange={(e) => update(s.id, { label: e.target.value })} onClick={(e) => e.stopPropagation()} />
                      )}
                      <span className="seg-time">{timecode(s.output_in)}<span className="arrow">→</span>{timecode(s.output_out)}</span>
                    </div>
                    {i > 0 && s.transition !== "cut" && (
                      <div className="seg-transition">
                        {s.transition === "dissolve" ? "Dissolve" : "Dip to black"} · {s.transition_duration.toFixed(1)}s
                      </div>
                    )}
                    {!locked ? (
                      <>
                        <div className="seg-grid" onClick={(e) => e.stopPropagation()}>
                          <div className="field">
                            <span className="field-label">Source clip</span>
                            <select className="select" value={s.media_id} onChange={(e) => {
                              const nm = mediaById[e.target.value];
                              const d = nm?.meta.duration ?? 0;
                              update(s.id, { media_id: e.target.value, source_in: Math.min(s.source_in, Math.max(0, d - 0.5)), source_out: Math.min(s.source_out, d) });
                            }}>
                              {project.media.map((mm) => <option key={mm.id} value={mm.id}>{mm.display_name}</option>)}
                            </select>
                          </div>
                          <div className="field">
                            <span className="field-label">Source in</span>
                            <TimeInput label="Source in" value={s.source_in} onCommit={(v) => update(s.id, { source_in: v })} />
                          </div>
                          <div className="field">
                            <span className="field-label">Source out</span>
                            <TimeInput label="Source out" value={s.source_out} onCommit={(v) => update(s.id, { source_out: Math.min(v, m?.meta.duration ?? v) })} />
                          </div>
                          <div className="field">
                            <span className="field-label">Transition in</span>
                            <div className="row gap-s">
                              <select className="select" value={i === 0 ? "cut" : s.transition} disabled={i === 0}
                                onChange={(e) => update(s.id, { transition: e.target.value as Transition })}>
                                {TRANSITIONS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                              </select>
                              {i > 0 && s.transition !== "cut" && (
                                <input className="input mono" style={{ width: 58 }} aria-label="Transition seconds"
                                  defaultValue={s.transition_duration} key={`${s.id}-${s.transition_duration}`}
                                  onBlur={(e) => { const v = Number(e.target.value); if (isFinite(v) && v > 0) update(s.id, { transition_duration: Math.min(3, v) }); }} />
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="seg-notes" onClick={(e) => e.stopPropagation()}>
                          <textarea className="textarea" rows={1} placeholder="Notes / instructions for this segment" value={s.notes} maxLength={600}
                            onChange={(e) => update(s.id, { notes: e.target.value })} />
                        </div>
                      </>
                    ) : (
                      <div className="media-meta" style={{ marginTop: 6 }}>
                        <span>{m?.display_name ?? "Missing clip"}</span>
                        <span>{s.source_in.toFixed(2)} → {s.source_out.toFixed(2)}s</span>
                        {s.notes && <span style={{ fontFamily: "var(--font-sans)" }}>{s.notes}</span>}
                      </div>
                    )}
                  </div>
                  {!locked && (
                    <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                      <button className="btn ghost icon-only" title="Move up" onClick={() => move(i, -1)} disabled={i === 0}><IconUp /></button>
                      <button className="btn ghost icon-only" title="Move down" onClick={() => move(i, 1)} disabled={i === segs.length - 1}><IconDown /></button>
                      <button className="btn ghost icon-only danger" title="Remove segment" onClick={() => persist(segs.filter((x) => x.id !== s.id))}><IconTrash /></button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="plan-bar">
            {!locked && <button className="btn" onClick={addSegment}><IconPlus /> Add Segment</button>}
            <label className="toggle">
              <input type="checkbox" checked={fades.in} disabled={locked} onChange={(e) => persist(segs, { ...fades, in: e.target.checked })} />
              <span className="track" /> Fade in from black
            </label>
            <label className="toggle">
              <input type="checkbox" checked={fades.out} disabled={locked} onChange={(e) => persist(segs, { ...fades, out: e.target.checked })} />
              <span className="track" /> Fade out to black
            </label>
            <div className="spacer" />
            {!approved && (
              <button className="btn primary lg" onClick={approve} disabled={!!job || segs.length === 0}>
                <IconCheck /> Approve Plan
              </button>
            )}
          </div>
        </>
      ) : (
        !planJob && (
          <div className="empty-state" style={{ border: "1px solid var(--line)", borderRadius: 12 }}>
            <h3>No edit plan yet</h3>
            <p style={{ maxWidth: 440, margin: "0 auto" }}>
              Generate a proposed sequence from your instructions, or build one by hand.
              Nothing is rendered until you approve the plan.
            </p>
            <button className="btn" style={{ marginTop: 16 }} onClick={addSegment} disabled={project.media.length === 0}>
              <IconPlus /> Add Segment Manually
            </button>
          </div>
        )
      )}
    </div>
  );
}
