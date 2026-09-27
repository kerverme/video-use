import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Isolated workspace, no API keys, no access token — set before server imports.
_WS = tempfile.mkdtemp(prefix="cv-test-")
os.environ["CLOUD_VIDEO_WORKSPACE"] = _WS
os.environ["CLOUD_VIDEO_CHUNK_MB"] = "1"
for key in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "CLOUD_VIDEO_ACCESS_TOKEN"):
    os.environ[key] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_clip(path: Path, seconds: float = 4.0, size: str = "640x360", rate: int = 24, audio: bool = False) -> Path:
    """Synthetic test-pattern clip (a fixture, not user media)."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="session")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    return {
        "silent": make_clip(d / "Exterior Shot.mp4", 4.0),
        "audio": make_clip(d / "entrance.mov", 3.0, size="480x270", rate=30, audio=True),
    }


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        yield c
