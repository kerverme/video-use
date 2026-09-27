# CLOUD VIDEO

A private web workspace for AI-assisted video editing, built on the
[video-use](https://github.com/browser-use/video-use) engine that lives in this
repository's root (`SKILL.md`, `helpers/`). Upstream files are left untouched,
so the fork can keep pulling from browser-use/video-use.

```
Media → Edit Instructions → Analyze → Proposed Edit Plan → Review → Approve → Render → Output versions
```

## How it relates to video-use

video-use is an *agent skill*. A coding agent reads `SKILL.md` and drives the
Python helpers. It has no LLM calls of its own and needs only `ffmpeg` plus an
optional ElevenLabs key. CLOUD VIDEO takes the agent's place and keeps
video-use as the engine:

| video-use step | CLOUD VIDEO |
|---|---|
| Inventory (`ffprobe`) | on upload: metadata and thumbnail (`server/media.py`) |
| Transcribe → pack (`transcribe.py`, `pack_transcripts.py`) | **Analysis** job, runs only with `ELEVENLABS_API_KEY` and speech audio |
| On-demand visuals (`timeline_view.py`) | filmstrip per clip in the Analysis job, plus keyframes for the planner |
| "LLM reasons → strategy → wait for confirmation" | **Generate Edit Plan** (Claude API), shown as a draft; **Approve** is mandatory |
| EDL → `render.py` | approved plan → `intermediate/edl.json` → **Render** job |
| Hard rules: per-segment extract, 30 ms audio fades, lossless concat, HDR tone-map, two-pass loudnorm | reused directly from `helpers/render.py` and `helpers/grade.py` |

Dissolves and dips to black are the one addition. video-use's concat path
only does hard cuts, so plans with dissolves are assembled with a single
`xfade`/`acrossfade` pass over the extracted segments.

## Architecture

```
studio/
  server/            FastAPI (Python): the only backend process
    main.py          routes; serves the static frontend on the same port
    engine.py        video-use bridge: ANALYSIS and RENDERING (kept separate)
    planner.py       Claude edit planning (structured JSON output)
    uploads.py       chunked, resumable uploads streamed to disk
    jobs.py          background job runner (progress, cancel, restart recovery)
    store.py         project.json metadata store (atomic writes)
    media.py         ffprobe + thumbnails
    presets.py       ARCHITECTURAL FILM preset
    security.py      id/filename validation, path containment
    auth.py          optional access token
  web/               Next.js + TypeScript, statically exported to web/out
  tests/             pytest (unit + end-to-end renders on synthetic clips)
workspace/           runtime data (git-ignored; CLOUD_VIDEO_WORKSPACE)
  projects/<id>/{input,assets,intermediate,output,project.json}
  temp/uploads/      in-flight upload parts
```

There is one process and one port, with no database and no microservices.
Jobs run on a small in-process thread pool, and their state lives in
`project.json`, so the UI just polls.

## Running

```bash
cp studio/.env.example studio/.env   # add keys (see below)
studio/run.sh                        # builds the frontend once, serves on :8000
```

Requirements: `ffmpeg`/`ffprobe`, `uv`, and Node.js 20+ for the frontend
build. For frontend development, run `npm run dev` in `studio/web` (port 3000;
API calls are proxied to :8000).

Tests:

```bash
cd studio && uv run pytest              # 34 backend tests, including real renders
cd studio/web && npm run typecheck && npm run build
```

## API keys

| Variable | Status | Used for |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Required for AI plans** | Generate Edit Plan (Claude). Without it the app shows *Configuration Required*; manual plans and rendering still work. |
| `ELEVENLABS_API_KEY` | Optional | video-use's Scribe transcription (speech-driven cuts). Blender renders are analyzed visually. video-use reads this from the repo-root `.env` or the environment; CLOUD VIDEO passes it through. |
| `CLOUD_VIDEO_ACCESS_TOKEN` | Required when public | Single-user access token (cookie session). |

Keys are read server-side only. The Settings page shows configured or not,
never the values.

## Large files

Uploads use a chunked, resumable protocol (`server/uploads.py`,
`web/lib/upload.ts`):

- The browser slices the file (`File.slice`) and PUTs 8 MB chunks with their
  byte offset. Nothing reads the whole video into memory, in the browser or on
  the server.
- The server appends each chunk straight to a `.part` file. A chunk must start
  exactly at the current end of that file, so retried chunks are detected
  (409) and a dropped connection resumes from the server's offset.
- On completion the server checks the container magic bytes, validates the
  file with ffprobe, and atomically renames it into `input/` (read-only). It
  then creates a thumbnail. Originals are never transcoded or modified.
- Small chunks stay under the request-body limits of common reverse proxies
  and CDNs, such as Cloudflare's 100 MB cap.

Limits: `CLOUD_VIDEO_MAX_UPLOAD_GB` (default 50 GB per file), and uploads are
refused if they would leave less than `CLOUD_VIDEO_MIN_FREE_GB` free.

## Where to host it

A Claude Code Cloud session is a good place to *build and test* this app. It
is not a place to *use* it:

- **No inbound access.** The container is outbound-only, so there is no port
  forwarding or public preview URL for your browser to reach the server.
- **Ephemeral storage.** The container is reclaimed after inactivity, and
  uploaded footage and renders would be lost.
- **Limited disk.** There is roughly 30 GB of writable space per session,
  which is small for 4K masters plus renders.

Run it where it gets a URL and a persistent disk, using the included image:

```bash
docker build -f studio/Dockerfile -t cloud-video .
docker run -p 8000:8000 -v cloud-video-data:/data --env-file studio/.env cloud-video
```

On a PaaS (Railway, Fly.io, Render, or a VPS), set the Dockerfile path to
`studio/Dockerfile` and mount a volume at `/data`. Set
`CLOUD_VIDEO_ACCESS_TOKEN` along with the API keys. The server honours
`$PORT`.

Rendering is CPU-only (libx264). A 75-second 1080p render at *High* takes a
few minutes on 2–4 vCPUs, and 4K or *Maximum* take several times longer.

## Security notes

- Project, media, and upload ids are validated (`^[a-z0-9]{6,40}$`), and every
  path is checked to resolve inside its root.
- Filenames are sanitized to a safe basename. Only `.mp4` and `.mov` are
  accepted, and the content is verified with ffprobe.
- Every ffmpeg and helper call uses an argument list, never a shell string.
  Your prompt only ever goes into the Claude API request body. Burned-in labels
  reach ffmpeg through `textfile=`, never through the filter string.
- Render settings are enums validated server-side. Plan times are clamped to
  clip durations.
- API responses carry no absolute server paths. Security headers and a CSP are
  set on every response.
