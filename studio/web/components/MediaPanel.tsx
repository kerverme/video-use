"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { bytes, timecode } from "@/lib/format";
import type { MediaItem, Project, Selection } from "@/lib/types";
import { isAcceptedVideo, uploadFile, type UploadHandle } from "@/lib/upload";
import { IconDown, IconFilm, IconGrip, IconTrash, IconUp, IconUpload, IconX } from "./Icons";
import { useToast } from "./Toasts";

interface QueueItem {
  key: string;
  file: File;
  sent: number;
  rate: number;
  stage: "queued" | "uploading" | "processing" | "error";
  error?: string;
  handle?: UploadHandle;
}

interface Props {
  project: Project;
  onProject: (p: Project) => void;
  selection: Selection;
  onSelect: (s: Selection) => void;
  busy: boolean;
}

export function MediaPanel({ project, onProject, selection, onSelect, busy }: Props) {
  const toast = useToast();
  const [over, setOver] = useState(false);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const running = useRef(false);
  const [drag, setDrag] = useState<{ id: string; target?: string; after?: boolean } | null>(null);

  const patch = (key: string, fields: Partial<QueueItem>) =>
    setQueue((q) => q.map((x) => (x.key === key ? { ...x, ...fields } : x)));

  // Process the queue one file at a time (a single stream saturates the link).
  useEffect(() => {
    if (running.current) return;
    const next = queue.find((q) => q.stage === "queued");
    if (!next) return;
    running.current = true;
    const handle = uploadFile(project.id, next.file, {
      onProgress: (sent, _total, rate) => patch(next.key, { sent, rate }),
      onStage: (stage) => patch(next.key, { stage }),
    });
    patch(next.key, { stage: "uploading", handle });
    handle.done
      .then((p) => {
        onProject(p);
        setQueue((q) => q.filter((x) => x.key !== next.key));
      })
      .catch((e: Error) => {
        if (e.message === "Cancelled") setQueue((q) => q.filter((x) => x.key !== next.key));
        else patch(next.key, { stage: "error", error: e.message });
      })
      .finally(() => {
        running.current = false;
        setQueue((q) => [...q]); // kick the effect for the next file
      });
  }, [queue, project.id, onProject]);

  const active = queue.some((q) => q.stage !== "error");
  useEffect(() => {
    if (!active) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);

  const addFiles = (files: FileList | File[]) => {
    const list = Array.from(files);
    const bad = list.filter((f) => !isAcceptedVideo(f));
    if (bad.length) toast(`Skipped ${bad.map((f) => f.name).join(", ")}: only MP4 and MOV are supported.`, "error");
    const good = list.filter(isAcceptedVideo);
    setQueue((q) => [...q, ...good.map((file) => ({
      key: `${file.name}-${file.size}-${Math.random()}`, file, sent: 0, rate: 0, stage: "queued" as const,
    }))]);
  };

  const rename = async (m: MediaItem, name: string) => {
    const clean = name.trim();
    if (!clean || clean === m.display_name) return;
    try { onProject(await api.renameMedia(project.id, m.id, clean)); } catch (e) { toast((e as Error).message, "error"); }
  };

  const remove = async (m: MediaItem) => {
    const inPlan = project.plan.segments.some((s) => s.media_id === m.id);
    if (!confirm(`Remove “${m.display_name}” from this project?${inPlan ? "\n\nIt is used in the edit plan; those segments will be removed too." : ""}\n\nThe project's stored copy is deleted. Your own original file is not affected.`)) return;
    try {
      onProject(await api.removeMedia(project.id, m.id));
      if (selection?.kind === "media" && selection.id === m.id) onSelect(null);
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const reorder = async (ids: string[]) => {
    const prev = project;
    onProject({ ...project, media: ids.map((id) => project.media.find((m) => m.id === id)!) });
    try { onProject(await api.reorderMedia(project.id, ids)); } catch (e) { onProject(prev); toast((e as Error).message, "error"); }
  };

  const move = (idx: number, delta: number) => {
    const ids = project.media.map((m) => m.id);
    const j = idx + delta;
    if (j < 0 || j >= ids.length) return;
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    reorder(ids);
  };

  const onRowDrop = () => {
    if (!drag?.target || drag.target === drag.id) return setDrag(null);
    const ids = project.media.map((m) => m.id).filter((id) => id !== drag.id);
    let at = ids.indexOf(drag.target);
    if (drag.after) at += 1;
    ids.splice(at, 0, drag.id);
    setDrag(null);
    reorder(ids);
  };

  const isFileDrag = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes("Files");
  const empty = project.media.length === 0 && queue.length === 0;

  return (
    <div
      onDragOver={(e) => { if (isFileDrag(e)) { e.preventDefault(); setOver(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(false); }}
      onDrop={(e) => { if (isFileDrag(e)) { e.preventDefault(); setOver(false); addFiles(e.dataTransfer.files); } }}
    >
      <input ref={inputRef} type="file" accept=".mp4,.mov,video/mp4,video/quicktime" multiple hidden
        onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />

      {empty ? (
        <div className={`dropzone ${over ? "over" : ""}`} onClick={() => inputRef.current?.click()} role="button" tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}>
          <div className="drop-icon"><IconUpload size={18} /></div>
          <div className="dropzone-title">Drop MP4 or MOV files here</div>
          <div>or <span style={{ color: "var(--text)" }}>browse</span> to add media. Large files are uploaded in resumable chunks.</div>
          <div style={{ marginTop: 18 }}>
            <button className="btn" onClick={(e) => { e.stopPropagation(); inputRef.current?.click(); }}>
              <IconUpload /> Add Media
            </button>
          </div>
        </div>
      ) : (
        <div className={`dropzone compact ${over ? "over" : ""}`} onClick={() => inputRef.current?.click()} role="button" tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}>
          <IconUpload /> <span>Drop more clips, or click to add</span>
        </div>
      )}

      <div className="media-list">
        {project.media.map((m, i) => {
          const selected = selection?.kind === "media" && selection.id === m.id;
          const dropCls = drag?.target === m.id && drag.id !== m.id ? (drag.after ? "drop-after" : "drop-before") : "";
          return (
            <div key={m.id}
              className={`media-row fade-in ${selected ? "selected" : ""} ${drag?.id === m.id ? "dragging" : ""} ${dropCls}`}
              onClick={() => onSelect({ kind: "media", id: m.id })}
              onDragOver={(e) => {
                if (!drag) return;
                e.preventDefault();
                const r = e.currentTarget.getBoundingClientRect();
                setDrag({ ...drag, target: m.id, after: e.clientY > r.top + r.height / 2 });
              }}
              onDrop={(e) => { if (drag) { e.preventDefault(); e.stopPropagation(); onRowDrop(); } }}
            >
              <div className="handle" draggable title="Drag to reorder"
                onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", m.id); setDrag({ id: m.id }); }}
                onDragEnd={() => setDrag(null)}>
                <IconGrip />
              </div>
              <div className="thumb">
                {m.thumbnail_url ? <img src={m.thumbnail_url} alt="" loading="lazy" draggable={false} /> : <div className="ph"><IconFilm /></div>}
                <span className="dur">{timecode(m.meta.duration)}</span>
              </div>
              <div style={{ minWidth: 0 }}>
                <input className="input inline media-name" defaultValue={m.display_name} key={m.display_name}
                  aria-label="Display name" maxLength={120} onClick={(e) => e.stopPropagation()}
                  onBlur={(e) => rename(m, e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") { (e.target as HTMLInputElement).value = m.display_name; (e.target as HTMLInputElement).blur(); } }} />
                <div className="media-meta">
                  <span>{m.meta.duration?.toFixed(2)}s</span>
                  <span>{m.meta.width}×{m.meta.height}</span>
                  <span>{m.meta.fps_label} fps</span>
                  <span>{bytes(m.size)}</span>
                  {m.meta.video_codec && <span>{m.meta.video_codec.toUpperCase()}</span>}
                  <span style={{ color: "var(--ok)" }}>● Uploaded</span>
                </div>
              </div>
              <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                <button className="btn ghost icon-only" title="Move up" onClick={() => move(i, -1)} disabled={i === 0}><IconUp /></button>
                <button className="btn ghost icon-only" title="Move down" onClick={() => move(i, 1)} disabled={i === project.media.length - 1}><IconDown /></button>
                <button className="btn ghost icon-only danger" title="Remove" onClick={() => remove(m)} disabled={busy}><IconTrash /></button>
              </div>
            </div>
          );
        })}

        {queue.map((q) => (
          <div key={q.key} className="media-row fade-in">
            <div />
            <div className="thumb"><div className="ph">{q.stage === "error" ? <IconX /> : <div className="spinner" />}</div></div>
            <div style={{ minWidth: 0 }}>
              <div className="media-name truncate">{q.file.name}</div>
              {q.stage === "error" ? (
                <div className="media-meta" style={{ color: "var(--danger)" }}>{q.error}</div>
              ) : (
                <div className="upload-progress">
                  <div className={`progress ${q.stage === "processing" ? "indeterminate" : ""}`}>
                    <i style={{ width: `${(q.sent / q.file.size) * 100}%` }} />
                  </div>
                  <span>
                    {q.stage === "queued" && "Waiting…"}
                    {q.stage === "uploading" && `${Math.floor((q.sent / q.file.size) * 100)}% · ${bytes(q.sent)} / ${bytes(q.file.size)}${q.rate ? ` · ${bytes(q.rate)}/s` : ""}`}
                    {q.stage === "processing" && "Verifying · reading metadata · thumbnail"}
                  </span>
                </div>
              )}
            </div>
            <div className="row-actions" style={{ opacity: 1 }}>
              {q.stage !== "processing" && (
                <button className="btn ghost icon-only" title={q.stage === "error" ? "Dismiss" : "Cancel upload"}
                  onClick={() => { q.handle?.cancel(); setQueue((x) => x.filter((y) => y.key !== q.key)); }}>
                  <IconX />
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
