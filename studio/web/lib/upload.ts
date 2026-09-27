/**
 * Chunked, resumable uploader.
 *
 * The file is sliced with File.slice() and each chunk is PUT with its byte
 * offset, so the browser never reads the whole video into memory and the
 * server streams each chunk straight to disk. XHR is used (not fetch) because
 * it reports upload progress. A failed chunk is retried with backoff after
 * asking the server for its current offset, so dropped connections resume
 * instead of starting over.
 */
import { AUTH_EVENT, request } from "./api";
import type { Project } from "./types";

export interface UploadHandle {
  cancel: () => void;
  done: Promise<Project>;
}

export interface UploadCallbacks {
  onProgress: (sent: number, total: number, bytesPerSecond: number) => void;
  onStage?: (stage: "uploading" | "processing") => void;
}

const MAX_RETRIES = 6;

function putChunk(url: string, blob: Blob, onProgress: (loaded: number) => void, signal: { xhr?: XMLHttpRequest }) {
  return new Promise<{ offset: number }>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    signal.xhr = xhr;
    xhr.open("PUT", url);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => onProgress(e.loaded);
    xhr.onload = () => {
      if (xhr.status === 401) window.dispatchEvent(new Event(AUTH_EVENT));
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        let detail = `Upload failed (${xhr.status})`;
        try {
          const d = JSON.parse(xhr.responseText).detail;
          detail = typeof d === "string" ? d : d?.message ?? detail;
        } catch {
          /* ignore */
        }
        reject(Object.assign(new Error(detail), { status: xhr.status }));
      }
    };
    xhr.onerror = () => reject(Object.assign(new Error("Network error"), { status: 0 }));
    xhr.onabort = () => reject(Object.assign(new Error("Cancelled"), { status: -1 }));
    xhr.send(blob);
  });
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function uploadFile(projectId: string, file: File, cb: UploadCallbacks): UploadHandle {
  let cancelled = false;
  const signal: { xhr?: XMLHttpRequest } = {};
  let uploadId: string | null = null;
  const base = `/api/projects/${encodeURIComponent(projectId)}/uploads`;

  const done = (async () => {
    const start = await request<{ upload_id: string; chunk_size: number; offset: number }>(base, {
      method: "POST",
      json: { filename: file.name, size: file.size },
    });
    uploadId = start.upload_id;
    const chunkSize = start.chunk_size;
    let offset = start.offset;
    let retries = 0;
    const t0 = performance.now();

    while (offset < file.size) {
      if (cancelled) throw new Error("Cancelled");
      const end = Math.min(file.size, offset + chunkSize);
      try {
        const res = await putChunk(
          `${base}/${uploadId}?offset=${offset}`,
          file.slice(offset, end),
          (loaded) => {
            const sent = offset + loaded;
            const secs = (performance.now() - t0) / 1000;
            cb.onProgress(sent, file.size, secs > 0 ? sent / secs : 0);
          },
          signal,
        );
        offset = res.offset;
        retries = 0;
      } catch (err) {
        const status = (err as { status?: number }).status ?? 0;
        if (cancelled || status === -1) throw new Error("Cancelled");
        // 4xx other than an offset conflict is a real rejection; don't retry.
        if (status >= 400 && status < 500 && status !== 409 && status !== 408 && status !== 429) throw err;
        if (++retries > MAX_RETRIES) throw err;
        await sleep(Math.min(16000, 500 * 2 ** retries));
        const st = await request<{ offset: number }>(`${base}/${uploadId}`);
        offset = st.offset; // resume from what the server actually has
      }
    }
    cb.onStage?.("processing");
    return request<Project>(`${base}/${uploadId}/complete`, { method: "POST" });
  })();

  return {
    done,
    cancel: () => {
      cancelled = true;
      signal.xhr?.abort();
      if (uploadId) request(`${base}/${uploadId}`, { method: "DELETE" }).catch(() => {});
    },
  };
}

export const ACCEPTED_EXTENSIONS = [".mp4", ".mov"];
export const isAcceptedVideo = (f: File) => ACCEPTED_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext));
