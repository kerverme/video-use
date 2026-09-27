#!/usr/bin/env bash
# CLOUD VIDEO — start the web app (API + frontend on one port).
#
#   studio/run.sh                 build frontend if needed, serve on 0.0.0.0:8000
#   PORT=9000 studio/run.sh       different port
#   studio/run.sh --rebuild       force a frontend rebuild
set -euo pipefail
cd "$(dirname "$0")"

command -v ffmpeg >/dev/null || { echo "ffmpeg is required (apt-get install -y ffmpeg)"; exit 1; }
command -v ffprobe >/dev/null || { echo "ffprobe is required (ships with ffmpeg)"; exit 1; }
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }

uv sync --quiet

if [[ "${1:-}" == "--rebuild" || ! -f web/out/index.html ]]; then
  echo "Building frontend…"
  (cd web && { [[ -d node_modules ]] || npm ci; } && NEXT_TELEMETRY_DISABLED=1 npm run build)
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
echo "CLOUD VIDEO → http://${HOST}:${PORT}"
exec .venv/bin/uvicorn server.main:app --host "$HOST" --port "$PORT" --proxy-headers --forwarded-allow-ips='*' \
  --timeout-keep-alive 75
