"""Optional single-user access protection.

If CLOUD_VIDEO_ACCESS_TOKEN is set, every /api route (except health and
login) requires a session cookie obtained by presenting that token. The cookie
holds an HMAC of the token, never the token itself. Leave the variable unset
only when the server is reachable solely by you (e.g. localhost).
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import settings

COOKIE = "cv_session"
OPEN_PATHS = {"/api/health", "/api/auth/login", "/api/auth/status", "/api/auth/logout"}


def enabled() -> bool:
    return bool(settings.access_token)


def session_value() -> str:
    return hmac.new(settings.access_token.encode(), b"cloud-video-session-v1", hashlib.sha256).hexdigest()


def token_matches(candidate: str) -> bool:
    return enabled() and hmac.compare_digest(
        hashlib.sha256(candidate.encode()).digest(), hashlib.sha256(settings.access_token.encode()).digest())


def is_authenticated(request: Request) -> bool:
    if not enabled():
        return True
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), session_value())


async def middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in OPEN_PATHS and not is_authenticated(request):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return await call_next(request)
