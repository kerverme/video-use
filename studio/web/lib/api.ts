import type { Preset, Project, ProjectSummary, RenderSettings, Segment, SystemStatus } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

export const AUTH_EVENT = "cv:auth-required";
export const PROJECTS_EVENT = "cv:projects-changed";

function messageFrom(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  return fallback;
}

export async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const res = await fetch(path, {
    ...rest,
    credentials: "same-origin",
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...(rest.headers || {}) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_EVENT));
  }
  if (!res.ok) {
    let detail: unknown = undefined;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, messageFrom(detail, `Request failed (${res.status})`), detail);
  }
  return (await res.json()) as T;
}

export const notifyProjectsChanged = () => window.dispatchEvent(new Event(PROJECTS_EVENT));

const P = (id: string) => `/api/projects/${encodeURIComponent(id)}`;

export const api = {
  authStatus: () => request<{ required: boolean; authenticated: boolean }>("/api/auth/status"),
  login: (token: string) => request<{ ok: boolean }>("/api/auth/login", { method: "POST", json: { token } }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  status: () => request<SystemStatus>("/api/status"),
  presets: () => request<Preset[]>("/api/presets"),

  projects: () => request<ProjectSummary[]>("/api/projects"),
  createProject: (name: string) => request<Project>("/api/projects", { method: "POST", json: { name } }),
  project: (id: string) => request<Project>(P(id)),
  patchProject: (id: string, patch: Partial<Pick<Project, "name" | "prompt" | "preset" | "target_duration">>) =>
    request<Project>(P(id), { method: "PATCH", json: patch }),
  deleteProject: (id: string) => request<{ ok: boolean }>(P(id), { method: "DELETE" }),

  renameMedia: (id: string, mid: string, display_name: string) =>
    request<Project>(`${P(id)}/media/${mid}`, { method: "PATCH", json: { display_name } }),
  reorderMedia: (id: string, ids: string[]) => request<Project>(`${P(id)}/media/order`, { method: "PUT", json: { ids } }),
  removeMedia: (id: string, mid: string) => request<Project>(`${P(id)}/media/${mid}`, { method: "DELETE" }),

  analyze: (id: string) => request<Project>(`${P(id)}/analyze`, { method: "POST" }),
  generatePlan: (id: string) => request<Project>(`${P(id)}/plan/generate`, { method: "POST" }),
  savePlan: (id: string, plan: { segments: Segment[]; title?: string; fade_in: boolean; fade_out: boolean; fade_duration: number }) =>
    request<Project>(`${P(id)}/plan`, { method: "PUT", json: plan }),
  approvePlan: (id: string) => request<Project>(`${P(id)}/plan/approve`, { method: "POST" }),
  revisePlan: (id: string) => request<Project>(`${P(id)}/plan/revise`, { method: "POST" }),

  saveRenderSettings: (id: string, s: Partial<RenderSettings>) =>
    request<Project>(`${P(id)}/render-settings`, { method: "PUT", json: s }),
  render: (id: string) => request<Project>(`${P(id)}/render`, { method: "POST" }),
  cancelJob: (id: string) => request<{ cancelled: boolean }>(`${P(id)}/jobs/cancel`, { method: "POST" }),
};
