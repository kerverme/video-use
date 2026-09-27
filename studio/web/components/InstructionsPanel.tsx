"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Preset, Project } from "@/lib/types";
import { IconAlert, IconCheck, IconSparkle } from "./Icons";
import { useToast } from "./Toasts";

const PLACEHOLDER = `Create a 75-second cinematic architectural film from these clips.

Use slow, elegant pacing.
Prioritize smooth camera movement.
Avoid flashy transitions.
Use subtle cuts and dissolves.
Preserve architectural details.
Use minimal typography.
Create a quiet-luxury atmosphere.`;

interface Props {
  project: Project;
  onProject: (p: Project) => void;
  presets: Preset[];
  busy: boolean;
}

export function InstructionsPanel({ project, onProject, presets, busy }: Props) {
  const toast = useToast();
  const [prompt, setPrompt] = useState(project.prompt);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [duration, setDuration] = useState(project.target_duration ? String(project.target_duration) : "");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastSaved = useRef(project.prompt);
  const preset = presets.find((p) => p.id === project.preset);

  // Keep local state when switching projects.
  useEffect(() => {
    setPrompt(project.prompt);
    lastSaved.current = project.prompt;
    setDuration(project.target_duration ? String(project.target_duration) : "");
  }, [project.id]);

  useEffect(() => {
    setDuration(project.target_duration ? String(project.target_duration) : "");
  }, [project.target_duration]);

  const savePrompt = async (value: string) => {
    if (value === lastSaved.current) return;
    setSaveState("saving");
    try {
      const p = await api.patchProject(project.id, { prompt: value });
      lastSaved.current = value;
      onProject(p);
      setSaveState("saved");
    } catch (e) {
      setSaveState("idle");
      toast((e as Error).message, "error");
    }
  };

  const onChange = (value: string) => {
    setPrompt(value);
    setSaveState("idle");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => savePrompt(value), 700);
  };

  const choosePreset = async (id: string | null) => {
    try { onProject(await api.patchProject(project.id, { preset: id })); } catch (e) { toast((e as Error).message, "error"); }
  };

  const saveDuration = async () => {
    const n = duration.trim() ? Number(duration) : null;
    if (n !== null && (!isFinite(n) || n <= 0 || n > 3600)) return toast("Target duration must be between 1 and 3600 seconds.", "error");
    try { onProject(await api.patchProject(project.id, { target_duration: n })); } catch (e) { toast((e as Error).message, "error"); }
  };

  const generate = async () => {
    clearTimeout(timer.current);
    await savePrompt(prompt);
    try {
      onProject(await api.generatePlan(project.id));
      document.getElementById("plan")?.scrollIntoView({ behavior: "smooth" });
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const analyze = async () => {
    try { onProject(await api.analyze(project.id)); } catch (e) { toast((e as Error).message, "error"); }
  };

  const noMedia = project.media.length === 0;

  return (
    <div>
      <div className="preset-row">
        <button className={`preset-card ${!project.preset ? "on" : ""}`} onClick={() => choosePreset(null)}>
          <div className="preset-name">Custom</div>
          <div className="preset-desc">Your instructions only. No built-in direction.</div>
        </button>
        {presets.map((p) => (
          <button key={p.id} className={`preset-card ${project.preset === p.id ? "on" : ""}`} onClick={() => choosePreset(p.id)}>
            <div className="preset-name">{project.preset === p.id && <IconCheck size={13} />}{p.name}</div>
            <div className="preset-desc">{p.description} Typically {p.duration_range[0]}–{p.duration_range[1]}s.</div>
          </button>
        ))}
      </div>

      {preset && (
        <details className="advanced" style={{ marginTop: 0, marginBottom: 14, borderTop: 0, paddingTop: 0 }}>
          <summary><span className="chev">›</span> {preset.name} guidance is applied to the plan · view</summary>
          <div className="code-block" style={{ marginTop: 10, whiteSpace: "pre-wrap" }}>{preset.guidance}</div>
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn sm" onClick={() => onChange(prompt ? `${prompt}\n\n${preset.guidance}` : preset.guidance)}>
              Insert into instructions
            </button>
            <span className="hint">Typical spaces: {preset.spaces.join(", ")}</span>
          </div>
        </details>
      )}

      <div className="prompt-box">
        <div className="prompt-label">
          <span>Edit Instructions</span>
          <span style={{ letterSpacing: 0, textTransform: "none", fontWeight: 400 }}>
            {saveState === "saving" && "Saving…"}
            {saveState === "saved" && "Saved"}
            {saveState === "idle" && `${prompt.length.toLocaleString()} characters`}
          </span>
        </div>
        <textarea className="prompt-area" value={prompt} placeholder={PLACEHOLDER} maxLength={20000}
          onChange={(e) => onChange(e.target.value)} onBlur={() => savePrompt(prompt)} spellCheck />
        <div className="prompt-footer">
          <label className="duration-field">
            Target duration
            <input className="input mono" inputMode="numeric" value={duration} placeholder="auto"
              onChange={(e) => setDuration(e.target.value.replace(/[^0-9.]/g, ""))}
              onBlur={saveDuration} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
            sec
          </label>
          <div style={{ flex: 1 }} />
          {!project.config.planner && (
            <span className="chip warn" title="Set ANTHROPIC_API_KEY on the server">
              <IconAlert size={12} /> Configuration Required
            </span>
          )}
          <button className="btn" onClick={analyze} disabled={busy || noMedia}
            title="Scene detection, filmstrips and (if configured) transcription. Runs automatically before planning.">
            Analyze Media
          </button>
          <button className="btn accent lg" onClick={generate} disabled={busy || noMedia}>
            <IconSparkle /> GENERATE EDIT PLAN
          </button>
        </div>
      </div>
      <p className="hint" style={{ marginTop: 10 }}>
        Generating a plan never renders. You review, adjust and approve the proposed sequence first.
      </p>
    </div>
  );
}
