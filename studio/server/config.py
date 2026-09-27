"""Runtime configuration for CLOUD VIDEO.

All settings come from environment variables, optionally loaded from
`studio/.env` and then the video-use repo-root `.env` (the file video-use's own
helpers read for ELEVENLABS_API_KEY). Real environment variables always win.
Secret values are only ever held server-side; nothing here is sent to the
browser except booleans saying whether a service is configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = STUDIO_DIR.parent  # the video-use checkout
HELPERS_DIR = REPO_ROOT / "helpers"
WEB_OUT_DIR = STUDIO_DIR / "web" / "out"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader. Never overrides variables that are already set."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ and value:
            os.environ[key] = value


_load_dotenv(STUDIO_DIR / ".env")
_load_dotenv(REPO_ROOT / ".env")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    workspace_dir: Path
    max_upload_bytes: int
    chunk_bytes: int
    min_free_bytes: int
    planner_model: str
    access_token: str

    @property
    def projects_dir(self) -> Path:
        return self.workspace_dir / "projects"

    @property
    def temp_dir(self) -> Path:
        return self.workspace_dir / "temp"

    @property
    def uploads_tmp_dir(self) -> Path:
        return self.temp_dir / "uploads"


def load_settings() -> Settings:
    workspace = Path(os.environ.get("CLOUD_VIDEO_WORKSPACE", REPO_ROOT / "workspace")).resolve()
    return Settings(
        workspace_dir=workspace,
        max_upload_bytes=_int_env("CLOUD_VIDEO_MAX_UPLOAD_GB", 50) * 1024**3,
        chunk_bytes=_int_env("CLOUD_VIDEO_CHUNK_MB", 8) * 1024**2,
        min_free_bytes=_int_env("CLOUD_VIDEO_MIN_FREE_GB", 2) * 1024**3,
        planner_model=os.environ.get("CLOUD_VIDEO_PLANNER_MODEL", "claude-opus-5").strip() or "claude-opus-5",
        access_token=os.environ.get("CLOUD_VIDEO_ACCESS_TOKEN", "").strip(),
    )


settings = load_settings()


def anthropic_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def elevenlabs_key() -> str:
    return os.environ.get("ELEVENLABS_API_KEY", "").strip()


def ensure_dirs() -> None:
    for d in (settings.projects_dir, settings.uploads_tmp_dir):
        d.mkdir(parents=True, exist_ok=True)
