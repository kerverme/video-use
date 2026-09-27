export function timecode(seconds: number | null | undefined, withFraction = false): string {
  if (seconds == null || !isFinite(seconds)) return "--:--";
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  const whole = Math.floor(sec);
  const base = `${String(m).padStart(2, "0")}:${String(whole).padStart(2, "0")}`;
  if (!withFraction) return base;
  return `${base}.${String(Math.floor((sec - whole) * 10))}`;
}

export function seconds(n: number | null | undefined, digits = 1): string {
  if (n == null) return "—";
  return `${n.toFixed(digits)}s`;
}

export function bytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

export function resolution(w?: number, h?: number): string {
  if (!w || !h) return "—";
  return `${w}×${h}`;
}

export function relativeDate(ts: number | null | undefined): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "Just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
}

export function fullDate(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function parseTime(input: string): number | null {
  // Accepts "12.5", "0:12.5", "1:02:03"
  const t = input.trim();
  if (!t) return null;
  const parts = t.split(":").map((p) => p.trim());
  if (parts.some((p) => p === "" || isNaN(Number(p)))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

export const pad2 = (n: number) => String(n).padStart(2, "0");
