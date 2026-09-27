"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, notifyProjectsChanged } from "@/lib/api";
import { relativeDate } from "@/lib/format";
import type { ProjectSummary } from "@/lib/types";
import { IconFilm, IconPlus } from "@/components/Icons";
import { useToast } from "@/components/Toasts";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [creating, setCreating] = useState(false);
  const router = useRouter();
  const toast = useToast();

  useEffect(() => {
    api.projects().then(setProjects).catch((e) => toast((e as Error).message, "error"));
  }, [toast]);

  const create = async () => {
    setCreating(true);
    try {
      const p = await api.createProject("Untitled Project");
      notifyProjectsChanged();
      router.push(`/project/?id=${p.id}`);
    } catch (e) {
      toast((e as Error).message, "error");
      setCreating(false);
    }
  };

  return (
    <div className="scroll">
      <div className="home fade-in">
        <div className="eyebrow">Workspace</div>
        <h1 className="page-title">Projects</h1>
        <div className="meta-line">
          <span>Upload footage, describe the film, approve the plan, render.</span>
        </div>

        <div className="grid-projects">
          <button className="proj-card" onClick={create} disabled={creating}
            style={{ background: "none", border: 0, padding: 0, textAlign: "left" }}>
            <div className="proj-cover proj-new">
              <div style={{ display: "grid", placeItems: "center", gap: 8 }}>
                {creating ? <div className="spinner" /> : <IconPlus size={20} />}
              </div>
            </div>
            <div className="proj-name">New Project</div>
            <div className="proj-meta">Start from empty footage bin</div>
          </button>

          {projects?.map((p) => (
            <Link key={p.id} href={`/project/?id=${p.id}`} className="proj-card">
              <div className="proj-cover">
                {p.thumbnail ? <img src={p.thumbnail} alt="" loading="lazy" /> : <IconFilm size={22} />}
              </div>
              <div className="proj-name truncate">{p.name}</div>
              <div className="proj-meta">
                {p.media_count} clip{p.media_count === 1 ? "" : "s"}
                {p.output_count > 0 && ` · ${p.output_count} version${p.output_count === 1 ? "" : "s"}`}
                {" · "}{relativeDate(p.updated_at)}
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
