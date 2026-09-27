"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, notifyProjectsChanged, PROJECTS_EVENT } from "@/lib/api";
import type { ProjectSummary } from "@/lib/types";
import { IconFilm, IconFolder, IconPlus, IconSettings } from "./Icons";
import { useToast } from "./Toasts";

export function Sidebar() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const pathname = usePathname();
  const params = useSearchParams();
  const router = useRouter();
  const toast = useToast();
  const currentId = pathname.startsWith("/project") ? params.get("id") : null;

  const load = useCallback(() => {
    api.projects().then(setProjects).catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    load();
    window.addEventListener(PROJECTS_EVENT, load);
    return () => window.removeEventListener(PROJECTS_EVENT, load);
  }, [load]);

  const newProject = async () => {
    try {
      const p = await api.createProject("Untitled Project");
      notifyProjectsChanged();
      router.push(`/project/?id=${p.id}`);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <aside className="sidebar">
      <Link href="/" className="brand" aria-label="CLOUD VIDEO home">
        <div className="brand-mark"><span /></div>
        <div className="brand-name">CLOUD VIDEO</div>
      </Link>

      <nav className="side-section">
        <Link href="/" className={`side-item ${pathname === "/" ? "active" : ""}`}>
          <IconFolder /> <span className="truncate">Projects</span>
          {projects && <span className="count">{projects.length}</span>}
        </Link>
        <button className="side-item" onClick={newProject}>
          <IconPlus /> <span className="truncate">New Project</span>
        </button>
      </nav>

      <div className="side-label">Recent Projects</div>
      <div className="side-recent">
        {projects?.length === 0 && <div className="side-empty">No projects yet</div>}
        {projects?.slice(0, 30).map((p) => (
          <Link key={p.id} href={`/project/?id=${p.id}`} className={`side-item ${currentId === p.id ? "active" : ""}`}>
            <IconFilm /> <span className="truncate">{p.name}</span>
          </Link>
        ))}
      </div>

      <div className="side-footer">
        <Link href="/settings/" className={`side-item ${pathname.startsWith("/settings") ? "active" : ""}`}>
          <IconSettings /> <span className="truncate">Settings</span>
        </Link>
      </div>
    </aside>
  );
}
