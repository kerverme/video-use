"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { bytes } from "@/lib/format";
import type { SystemStatus } from "@/lib/types";

const STATE_LABEL: Record<string, string> = {
  ready: "Ready",
  not_configured: "Not configured",
  missing: "Missing",
  error: "Error",
};

export default function SettingsPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.status().then(setStatus).catch((e) => setError((e as Error).message));
  }, []);

  return (
    <div className="scroll">
      <div className="home fade-in">
        <div className="eyebrow">System</div>
        <h1 className="page-title">Settings</h1>
        <div className="meta-line"><span>Service status for this workspace. Secret values never leave the server.</span></div>

        {error && <div className="notice danger" style={{ marginTop: 24 }}>{error}</div>}
        {!status && !error && <div style={{ marginTop: 30 }}><div className="spinner" /></div>}

        {status && (
          <>
            <div className="settings-list">
              {status.services.map((s) => (
                <div key={s.key} className="settings-row">
                  <div className="settings-name">
                    {s.name}
                    {!s.required && <span className="muted" style={{ fontSize: 11.5 }}> · optional</span>}
                  </div>
                  <div className={`state ${s.state}`}><span className="dot" />{STATE_LABEL[s.state]}</div>
                  <div className="settings-detail">{s.detail}</div>
                </div>
              ))}
              <div className="settings-row">
                <div className="settings-name">Storage</div>
                <div className="state ready"><span className="dot" />{bytes(status.storage.free_bytes)} free</div>
                <div className="settings-detail">
                  of {bytes(status.storage.total_bytes)} · uploads up to {bytes(status.storage.max_upload_bytes)} per file,
                  streamed in {bytes(status.storage.chunk_bytes)} chunks · {status.formats.join(", ").toUpperCase()}
                </div>
              </div>
            </div>

            <h2 className="section-title" style={{ marginTop: 44, marginBottom: 12 }}>Configuration</h2>
            <p className="hint" style={{ maxWidth: 640 }}>
              Keys are read from environment variables, or from <span className="kbd">studio/.env</span> on the
              server (see <span className="kbd">studio/.env.example</span>). Restart the server after changing them.
            </p>
            <div className="code-block">{`# Required for GENERATE EDIT PLAN (Claude)
ANTHROPIC_API_KEY=

# Optional: speech transcription via video-use / ElevenLabs Scribe
ELEVENLABS_API_KEY=

# Strongly recommended whenever the server is reachable from the internet
CLOUD_VIDEO_ACCESS_TOKEN=`}</div>
          </>
        )}
      </div>
    </div>
  );
}
