"""End-to-end API tests: real uploads, ffprobe, ffmpeg renders on synthetic clips."""

import json
import subprocess
import time
from pathlib import Path

import pytest


def wait_job(client, pid, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = client.get(f"/api/projects/{pid}").json()
        if not p["active_job"]:
            return p
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def upload(client, pid, path: Path, chunk=1024 * 1024):
    data = path.read_bytes()
    r = client.post(f"/api/projects/{pid}/uploads", json={"filename": path.name, "size": len(data)})
    assert r.status_code == 200, r.text
    uid = r.json()["upload_id"]
    offset = 0
    while offset < len(data):
        piece = data[offset:offset + chunk]
        r = client.put(f"/api/projects/{pid}/uploads/{uid}?offset={offset}", content=piece)
        assert r.status_code == 200, r.text
        offset = r.json()["offset"]
    return client.post(f"/api/projects/{pid}/uploads/{uid}/complete")


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.fixture(scope="module")
def project(client, clips):
    p = client.post("/api/projects", json={"name": "Villa Test"}).json()
    r = upload(client, p["id"], clips["silent"], chunk=64 * 1024)
    assert r.status_code == 200, r.text
    r = upload(client, p["id"], clips["audio"])
    assert r.status_code == 200, r.text
    return r.json()


def test_status_reports_services(client):
    s = {x["key"]: x for x in client.get("/api/status").json()["services"]}
    assert s["ffmpeg"]["state"] == "ready"
    assert s["ffprobe"]["state"] == "ready"
    assert s["engine"]["state"] == "ready"
    assert s["planner"]["state"] == "not_configured"
    assert s["transcription"]["state"] == "not_configured"
    body = json.dumps(client.get("/api/status").json())
    assert "sk-" not in body


def test_project_directories_created(client, project):
    from server.config import settings
    root = settings.projects_dir / project["id"]
    for sub in ("input", "assets", "intermediate", "output"):
        assert (root / sub).is_dir()
    assert (root / "project.json").is_file()
    assert any(p["id"] == project["id"] for p in client.get("/api/projects").json())


def test_media_metadata_and_thumbnail(client, project):
    silent, audio = project["media"]
    assert silent["display_name"] == "Exterior Shot"
    assert silent["file"] == "Exterior Shot.mp4"
    assert silent["meta"]["width"] == 640 and silent["meta"]["height"] == 360
    assert silent["meta"]["fps_label"] == "24"
    assert abs(silent["meta"]["duration"] - 4.0) < 0.1
    assert audio["meta"]["audio_streams"] == 1 and audio["meta"]["fps_label"] == "30"
    r = client.get(silent["thumbnail_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    # Range requests work for scrubbing in the browser.
    r = client.get(silent["file_url"], headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    # No absolute server paths leak to the browser.
    assert "/home/" not in json.dumps(project) and "/tmp/" not in json.dumps(project)


def test_upload_rejects_bad_types(client, project, tmp_path):
    pid = project["id"]
    r = client.post(f"/api/projects/{pid}/uploads", json={"filename": "x.avi", "size": 10})
    assert r.status_code == 415
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"this is not a video at all" * 10)
    assert upload(client, pid, fake).status_code == 422
    r = client.post(f"/api/projects/{pid}/uploads", json={"filename": "big.mp4", "size": 10**15})
    assert r.status_code in (413, 507)


def test_upload_offset_mismatch_and_resume(client, project, clips):
    pid = project["id"]
    data = clips["silent"].read_bytes()
    uid = client.post(f"/api/projects/{pid}/uploads", json={"filename": "r.mp4", "size": len(data)}).json()["upload_id"]
    client.put(f"/api/projects/{pid}/uploads/{uid}?offset=0", content=data[:1000])
    r = client.put(f"/api/projects/{pid}/uploads/{uid}?offset=0", content=data[:1000])
    assert r.status_code == 409  # retried chunk detected
    assert client.get(f"/api/projects/{pid}/uploads/{uid}").json()["offset"] == 1000
    client.delete(f"/api/projects/{pid}/uploads/{uid}")


def test_traversal_ids_rejected(client, project):
    assert client.get("/api/projects/..%2F..%2Fetc").status_code == 404
    assert client.get(f"/api/projects/{project['id']}/media/..%2Fx/file").status_code == 404


def test_rename_and_reorder(client, project):
    pid = project["id"]
    a, b = [m["id"] for m in project["media"]]
    p = client.patch(f"/api/projects/{pid}/media/{a}", json={"display_name": "Exterior — Dawn"}).json()
    assert p["media"][0]["display_name"] == "Exterior — Dawn"
    p = client.put(f"/api/projects/{pid}/media/order", json={"ids": [b, a]}).json()
    assert [m["id"] for m in p["media"]] == [b, a]
    client.put(f"/api/projects/{pid}/media/order", json={"ids": [a, b]})


def test_generate_plan_requires_configuration(client, project):
    pid = project["id"]
    client.patch(f"/api/projects/{pid}", json={"preset": "architectural", "prompt": "Quiet film."})
    client.post(f"/api/projects/{pid}/plan/generate")
    p = wait_job(client, pid)
    assert p["last_job"]["status"] == "config_required"
    assert "ANTHROPIC_API_KEY" in p["last_job"]["error"]
    assert p["plan"]["status"] == "none"  # nothing faked
    assert p["target_duration"] == 75


def test_analysis_runs_video_use_helpers(client, project):
    pid = project["id"]
    client.post(f"/api/projects/{pid}/analyze")
    p = wait_job(client, pid)
    assert p["last_job"]["status"] == "done", p["last_job"]
    assert p["analysis"]["status"] == "done"
    assert any("Transcription not configured" in n for n in p["analysis"]["notes"])
    assert all(m["filmstrip_url"] for m in p["media"])
    assert client.get(p["media"][0]["filmstrip_url"]).status_code == 200


def test_render_requires_approval(client, project):
    pid = project["id"]
    assert client.post(f"/api/projects/{pid}/render").status_code == 400


def _manual_plan(client, pid, media, transition):
    a, b = media[0]["id"], media[1]["id"]
    return client.put(f"/api/projects/{pid}/plan", json={
        "title": "Test", "fade_in": True, "fade_out": True, "fade_duration": 0.5,
        "segments": [
            {"media_id": a, "source_in": 0.5, "source_out": 3.0, "label": "Exterior", "transition": "cut"},
            {"media_id": b, "source_in": 0.0, "source_out": 2.5, "label": "Entrance",
             "transition": transition, "transition_duration": 1.0},
        ]})


def test_plan_validation(client, project):
    pid = project["id"]
    r = client.put(f"/api/projects/{pid}/plan", json={"segments": [
        {"media_id": project["media"][0]["id"], "source_in": 2, "source_out": 2.1}]})
    assert r.status_code == 400


def test_render_cut_then_dissolve_versions(client, project):
    from server.config import settings
    pid = project["id"]
    media = project["media"]

    # v1: hard cut, mixed audio/no-audio sources, labels burned in, 1080p forced 25 fps.
    p = _manual_plan(client, pid, media, "cut").json()
    assert p["plan"]["status"] == "draft" and p["plan"]["total_duration"] == 5.0
    client.put(f"/api/projects/{pid}/render-settings",
               json={"resolution": "1080p", "fps": "25", "quality": "preview", "burn_labels": True})
    p = client.post(f"/api/projects/{pid}/plan/approve").json()
    assert p["plan"]["status"] == "approved"
    client.post(f"/api/projects/{pid}/render")
    p = wait_job(client, pid, timeout=300)
    assert p["last_job"]["status"] == "done", p["last_job"]
    v1 = p["outputs"][0]
    assert v1["file"] == "version-001.mp4" and (v1["width"], v1["height"]) == (1920, 1080)
    assert abs(v1["duration"] - 5.0) < 0.15
    out = settings.projects_dir / pid / "output" / "version-001.mp4"
    info = probe(out)
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
    assert (settings.projects_dir / pid / "intermediate" / "edl.json").is_file()
    edl = json.loads((settings.projects_dir / pid / "intermediate" / "edl.json").read_text())
    assert len(edl["ranges"]) == 2 and set(edl["sources"]) == {"Exterior Shot", "entrance"}

    # Editing the plan un-approves it.
    p = _manual_plan(client, pid, media, "dissolve").json()
    assert p["plan"]["status"] == "draft" and p["plan"]["total_duration"] == 4.0

    # v2: dissolve, square, source fps; v1 is kept.
    client.put(f"/api/projects/{pid}/render-settings", json={"aspect": "1:1", "resolution": "original",
                                                             "fps": "source", "burn_labels": False})
    client.post(f"/api/projects/{pid}/plan/approve")
    client.post(f"/api/projects/{pid}/render")
    p = wait_job(client, pid, timeout=300)
    assert p["last_job"]["status"] == "done", p["last_job"]
    assert [o["file"] for o in p["outputs"]] == ["version-002.mp4", "version-001.mp4"]
    v2 = p["outputs"][0]
    assert (v2["width"], v2["height"]) == (360, 360)
    assert abs(v2["duration"] - 4.0) < 0.15
    assert out.is_file()
    r = client.get(v2["download_url"])
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]


def test_remove_media_unapproves_plan(client, project):
    pid = project["id"]
    from server.config import settings
    mid = project["media"][1]["id"]
    stored = settings.projects_dir / pid / "input" / project["media"][1]["file"]
    assert stored.is_file()
    p = client.delete(f"/api/projects/{pid}/media/{mid}").json()
    assert len(p["media"]) == 1 and not stored.exists()
    assert p["plan"]["status"] == "draft"
    assert all(s["media_id"] != mid for s in p["plan"]["segments"])


def test_access_token(monkeypatch, client):
    from server import auth, config
    new =config.Settings(**{**config.settings.__dict__, "access_token": "s3cret"})
    monkeypatch.setattr(auth, "settings", new)
    client.cookies.clear()
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/auth/login", json={"token": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"token": "s3cret"}).status_code == 200
    assert client.get("/api/projects").status_code == 200
    client.cookies.clear()
