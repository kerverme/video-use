# CLOUD VIDEO: production image (API + frontend + video-use + ffmpeg).
#
# Build from the repository root (the image needs video-use's helpers/):
#   docker build -f studio/Dockerfile -t cloud-video .
#   docker run -p 8000:8000 -v cloud-video-data:/data --env-file studio/.env cloud-video
#
# Projects are stored in /data/workspace, so mount a persistent volume at /data.

# ---- frontend (static export) ----------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY studio/web/package.json studio/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY studio/web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- runtime -----------------------------------------------------------------
# Ubuntu 24.04: Python 3.12 + ffmpeg 6.1 (the combination the test suite runs on).
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core python3 python3-pip ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip3 install --no-cache-dir --break-system-packages uv
WORKDIR /app
# video-use itself (engine) + the studio server
COPY pyproject.toml README.md LICENSE SKILL.md ./
COPY helpers/ helpers/
COPY skills/ skills/
COPY studio/pyproject.toml studio/uv.lock studio/
RUN cd studio && UV_PYTHON_DOWNLOADS=never uv sync --frozen --no-dev
COPY studio/server/ studio/server/
COPY --from=web /web/out studio/web/out

ENV CLOUD_VIDEO_WORKSPACE=/data/workspace \
    PYTHONUNBUFFERED=1 \
    PORT=8000
VOLUME /data
EXPOSE 8000
WORKDIR /app/studio
# Hosting platforms usually inject $PORT.
CMD ["sh", "-c", "exec .venv/bin/uvicorn server.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75"]
