"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, notifyProjectsChanged } from "@/lib/api";
import { fullDate } from "@/lib/format";
import type { Preset, Project, Selection } from "@/lib/types";
import { MediaPanel } from "@/components/MediaPanel";
import { InstructionsPanel } from "@/components/InstructionsPanel";
import { PlanPanel } from "@/components/PlanPanel";
import { RenderPanel } from "@/components/RenderPanel";
import { OutputPanel } from "@/components/OutputPanel";
import { Inspector } from "@/components/Inspector";
import { IconTrash } from "@/components/Icons";
import { useToast } from "@/components/Toasts";

const STEPS = [
  { id: "media", label: "Media" },
  { id: "instructions", label: "Instructions" },
  { id: "plan", label: "Edit Plan" },
  { id: "render", label: "Render" },
  { id: "output", label: "Output" },
] as const;

export default function ProjectPage() {
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const router = useRouter();
  const toast = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [missing, setMissing] = useState(false);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const prevJob = useRef<string | null>(null);

  const onProject = useCallback((p: Project) => setProject(p), []);

  useEffect(() => {
    api.presets().then(setPresets).catch(() => {});
  }, []);

  // Reset when switching projects.
  useEffect(() => {
    setProject(null);
    setMissing(false);
    setSelection(null);
    prevJob.current = null;
  }, [id]);

  // Poll: every second while a job runs, every 5s otherwise. Restarts when a
  // job starts so progress shows up immediately.
  const busyFlag = !!project?.active_job;
  useEffect(() => {
    if (!id) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const p = await api.project(id);
        if (!alive) return;
        setProject(p);
        timer = setTimeout(tick, p.active_job ? 1000 : 5000);
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 404) setMissing(true);
        else timer = setTimeout(tick, 5000);
      }
    };
    timer = setTimeout(tick, busyFlag ? 600 : 0);
    return () => { alive = false; clearTimeout(timer); };
  }, [id, busyFlag]);

  // React to job completion.
  useEffect(() => {
    if (!project) return;
    const active = project.active_job?.id ?? null;
    if (prevJob.current && !active && project.last_job?.id === prevJob.current) {
      const j = project.last_job;
      if (j.status === "done" && j.kind === "render" && project.outputs[0]) {
        setSelection({ kind: "output", id: project.outputs[0].id });
        toast(`${project.outputs[0].file} is ready.`);
        document.getElementById("output")?.scrollIntoView({ behavior: "smooth" });
      } else if (j.status === "done" && j.kind === "plan") {
        toast("Edit plan ready for review.");
      } else if (j.status === "done" && j.kind === "analyze") {
        toast("Analysis complete.");
      } else if (j.status === "error") {
        toast(`${j.kind === "render" ? "Render" : j.kind === "plan" ? "Planning" : "Analysis"} failed.`, "error");
      }
    }
    prevJob.current = active;
  }, [project, toast]);

  if (!id || missing) {
    return (
      <div className="center-screen">
        <div className="empty-state">
          <h3>Project not found</h3>
          <button className="btn" style={{ marginTop: 12 }} onClick={() => router.push("/")}>Back to projects</button>
        </div>
      </div>
    );
  }
  if (!project) return <div className="center-screen"><div className="spinner" /></div>;

  const job = project.active_job;
  const busy = !!job;
  const stepState = {
    media: project.media.length > 0,
    instructions: project.prompt.trim().length > 0 || !!project.preset,
    plan: project.plan.status === "approved",
    render: project.outputs.length > 0,
    output: project.outputs.length > 0,
  };
  const currentStep = STEPS.find((s) => !stepState[s.id])?.id ?? "output";

  const rename = async (name: string) => {
    const clean = name.trim();
    if (!clean || clean === project.name) return;
    try {
      setProject(await api.patchProject(project.id, { name: clean }));
      notifyProjectsChanged();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const remove = async () => {
    if (!confirm(`Delete “${project.name}” and all of its media, plans and renders? This cannot be undone.`)) return;
    try {
      await api.deleteProject(project.id);
      notifyProjectsChanged();
      router.push("/");
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const go = (sid: string) => document.getElementById(sid)?.scrollIntoView({ behavior: "smooth" });

  return (
    <div className="workspace">
      <div className="main-scroll">
        <div className="main-inner">
          <header className="page-head fade-in">
            <div className="row">
              <div className="eyebrow">Project</div>
              <button className="btn ghost sm danger" style={{ marginLeft: "auto" }} onClick={remove} disabled={busy} title="Delete project">
                <IconTrash size={13} /> Delete
              </button>
            </div>
            <input className="title-input" defaultValue={project.name} key={project.id + project.name} maxLength={120}
              aria-label="Project title" onBlur={(e) => rename(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
            <div className="meta-line">
              <span>Created {fullDate(project.created_at)}</span>
              <span>{project.media.length} clip{project.media.length === 1 ? "" : "s"}</span>
              <span>{project.outputs.length} version{project.outputs.length === 1 ? "" : "s"}</span>
            </div>
          </header>

          <nav className="rail" aria-label="Workflow">
            {STEPS.map((s, i) => (
              <span key={s.id} style={{ display: "contents" }}>
                {i > 0 && <span className="rail-sep" />}
                <button className={`rail-step ${stepState[s.id] ? "done" : ""} ${currentStep === s.id ? "current" : ""}`} onClick={() => go(s.id)}>
                  <span className="rail-dot">{stepState[s.id] ? "✓" : i + 1}</span>{s.label}
                </button>
              </span>
            ))}
          </nav>

          <section id="media" className="section">
            <div className="section-head">
              <span className="section-num">01</span><h2 className="section-title">Media</h2>
              <span className="section-sub">MP4 · MOV · originals are never modified</span>
            </div>
            <MediaPanel project={project} onProject={onProject} selection={selection} onSelect={setSelection} busy={busy} />
          </section>

          <section id="instructions" className="section">
            <div className="section-head">
              <span className="section-num">02</span><h2 className="section-title">Prompt / Edit Instructions</h2>
            </div>
            <InstructionsPanel project={project} onProject={onProject} presets={presets} busy={busy} />
          </section>

          <section id="plan" className="section">
            <div className="section-head">
              <span className="section-num">03</span><h2 className="section-title">Edit Plan</h2>
              {project.plan.title && <span className="section-sub">{project.plan.title}</span>}
              <span className="section-actions">
                {project.plan.status === "approved" && <span className="chip accent">Approved</span>}
                {project.plan.status === "draft" && <span className="chip">Draft · awaiting approval</span>}
              </span>
            </div>
            <PlanPanel project={project} onProject={onProject} selection={selection} onSelect={setSelection} job={job} />
          </section>

          <section id="render" className="section">
            <div className="section-head">
              <span className="section-num">04</span><h2 className="section-title">Render</h2>
            </div>
            <RenderPanel project={project} onProject={onProject} job={job} />
          </section>

          <section id="output" className="section">
            <div className="section-head">
              <span className="section-num">05</span><h2 className="section-title">Output</h2>
              <span className="section-sub">{project.outputs.length ? `${project.outputs.length} version${project.outputs.length > 1 ? "s" : ""}` : ""}</span>
            </div>
            <OutputPanel project={project} onProject={onProject} selection={selection} onSelect={setSelection} busy={busy} />
          </section>
        </div>
      </div>
      <Inspector project={project} selection={selection} job={job} />
    </div>
  );
}
