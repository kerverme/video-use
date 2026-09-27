export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled" | "config_required";

export interface Job {
  id: string;
  kind: "analyze" | "plan" | "render";
  status: JobStatus;
  stages: string[];
  stage: string | null;
  progress: number | null;
  message: string | null;
  error: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
}

export interface MediaMeta {
  duration: number | null;
  width: number;
  height: number;
  fps: number | null;
  fps_label: string;
  video_codec: string | null;
  pix_fmt: string | null;
  color_transfer: string | null;
  audio_streams: number;
  audio_codec: string | null;
  browser_playable: boolean;
}

export interface MediaItem {
  id: string;
  file: string;
  display_name: string;
  original_name: string;
  size: number;
  added_at: number;
  status: string;
  meta: MediaMeta;
  thumbnail_url: string | null;
  file_url: string;
  filmstrip_url: string | null;
  scene_count: number | null;
}

export type Transition = "cut" | "dissolve" | "dip_to_black";

export interface Segment {
  id: string;
  media_id: string;
  source_in: number;
  source_out: number;
  label: string;
  transition: Transition;
  transition_duration: number;
  notes: string;
  output_in?: number;
  output_out?: number;
  overlap?: number;
}

export interface Plan {
  status: "none" | "draft" | "approved";
  source?: "ai" | "manual";
  model?: string;
  title?: string;
  summary?: string;
  warnings?: string[];
  fade_in?: boolean;
  fade_out?: boolean;
  fade_duration?: number;
  segments: Segment[];
  total_duration: number;
  approved_at?: number | null;
}

export interface RenderSettings {
  resolution: "original" | "1080p" | "4k";
  aspect: "source" | "16:9" | "9:16" | "1:1";
  fps: "source" | "24" | "25" | "30" | "60";
  quality: "preview" | "high" | "maximum";
  grade: "none" | "subtle" | "neutral_punch" | "warm_cinematic" | "auto";
  fit: "crop" | "letterbox";
  audio: "keep" | "mute";
  loudnorm: boolean;
  burn_labels: boolean;
}

export interface OutputVersion {
  id: string;
  version: number;
  file: string;
  created_at: number;
  size: number;
  duration: number | null;
  width: number;
  height: number;
  fps_label: string;
  settings: RenderSettings;
  plan_title?: string;
  segment_count: number;
  file_url: string;
  download_url: string;
  thumbnail_url: string;
}

export interface Project {
  id: string;
  name: string;
  created_at: number;
  updated_at: number;
  preset: string | null;
  prompt: string;
  target_duration: number | null;
  media: MediaItem[];
  analysis: { status: "none" | "running" | "done" | "stale" | "error"; notes?: string[]; updated_at?: number | null };
  plan: Plan;
  render_settings: RenderSettings;
  outputs: OutputVersion[];
  active_job: Job | null;
  last_job: Job | null;
  config: { planner: boolean; transcription: boolean };
}

export interface ProjectSummary {
  id: string;
  name: string;
  created_at: number;
  updated_at: number;
  media_count: number;
  output_count: number;
  thumbnail: string | null;
}

export interface Preset {
  id: string;
  name: string;
  description: string;
  guidance: string;
  target_duration: number;
  duration_range: [number, number];
  spaces: string[];
}

export interface ServiceStatus {
  key: string;
  name: string;
  state: "ready" | "missing" | "error" | "not_configured";
  detail: string;
  required: boolean;
}

export interface SystemStatus {
  services: ServiceStatus[];
  storage: { free_bytes: number; total_bytes: number; max_upload_bytes: number; chunk_bytes: number };
  formats: string[];
}

export type Selection =
  | { kind: "media"; id: string }
  | { kind: "segment"; id: string }
  | { kind: "output"; id: string }
  | null;
