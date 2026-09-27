"use client";

import { useEffect, useState } from "react";
import { api, AUTH_EVENT } from "@/lib/api";
import { IconLock } from "./Icons";

/** Shows a token prompt when the server has CLOUD_VIDEO_ACCESS_TOKEN set. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"checking" | "ok" | "login" | "offline">("checking");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.authStatus()
      .then((s) => setState(s.required && !s.authenticated ? "login" : "ok"))
      .catch(() => setState("offline"));
    const onAuth = () => setState("login");
    window.addEventListener(AUTH_EVENT, onAuth);
    return () => window.removeEventListener(AUTH_EVENT, onAuth);
  }, []);

  if (state === "ok") return <>{children}</>;
  if (state === "checking") return <div className="center-screen"><div className="spinner" /></div>;
  if (state === "offline") {
    return (
      <div className="center-screen">
        <div className="empty-state">
          <h3>Server unavailable</h3>
          <p>The CLOUD VIDEO backend could not be reached. Start it with <span className="kbd">studio/run.sh</span>.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="center-screen">
      <form className="login-card fade-in" onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          await api.login(token);
          window.location.reload();
        } catch {
          setError("That token is not valid.");
        }
      }}>
        <div className="brand" style={{ padding: "0 0 24px" }}>
          <div className="brand-mark"><span /></div>
          <div className="brand-name">CLOUD VIDEO</div>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="token">Access token</label>
          <input id="token" className="input" type="password" autoFocus value={token}
            onChange={(e) => setToken(e.target.value)} autoComplete="current-password" />
        </div>
        {error && <p className="hint" style={{ color: "var(--danger)" }}>{error}</p>}
        <button className="btn primary block" style={{ marginTop: 14 }} disabled={!token}>
          <IconLock /> Unlock
        </button>
      </form>
    </div>
  );
}
