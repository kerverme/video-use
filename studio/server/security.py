"""Input validation: identifiers, filenames, and path containment.

Every path the server touches on behalf of a request is built from a validated
identifier and then checked to resolve inside its expected root, so a crafted
id or filename can never reach outside the workspace.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from pathlib import Path

from fastapi import HTTPException

ID_RE = re.compile(r"^[a-z0-9]{6,40}$")
ALLOWED_VIDEO_EXTS = {".mp4", ".mov"}
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._ -]+")


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_hex(6)


def check_id(value: str, what: str = "id") -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise HTTPException(status_code=404, detail=f"unknown {what}")
    return value


def safe_join(root: Path, *parts: str) -> Path:
    """Join and verify the result stays inside `root` (after resolving symlinks)."""
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*parts).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise HTTPException(status_code=400, detail="invalid path")
    return candidate


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Reduce an uploaded filename to a safe basename, preserving the extension."""
    name = unicodedata.normalize("NFKC", str(name or ""))
    # Drop any directory components from either separator style.
    name = name.replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = _UNSAFE_CHARS.sub("_", stem).strip(" ._") or "clip"
    ext = _UNSAFE_CHARS.sub("", ext).lower()
    stem = re.sub(r"[ _]{2,}", "_", stem)[: max_len - len(ext) - 1]
    return f"{stem}.{ext}" if ext else stem


def clean_text(value: object, max_len: int, multiline: bool = False) -> str:
    """Normalize user-supplied display text (names, labels, notes)."""
    text = unicodedata.normalize("NFKC", str(value if value is not None else ""))
    # Remove control characters (keep newlines/tabs for multiline fields).
    allowed = "\n\t" if multiline else ""
    text = "".join(ch for ch in text if ch in allowed or unicodedata.category(ch)[0] != "C")
    if not multiline:
        text = " ".join(text.split())
    return text.strip()[:max_len]


def is_allowed_video_name(name: str) -> bool:
    return Path(name).suffix.lower() in ALLOWED_VIDEO_EXTS


# ISO-BMFF (MP4 / QuickTime MOV) top-level atom types that may legitimately
# appear first in a file. Used as a cheap magic-byte check before ffprobe.
_ISO_BMFF_ATOMS = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot", b"uuid"}


def looks_like_iso_bmff(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except OSError:
        return False
    return len(head) >= 8 and head[4:8] in _ISO_BMFF_ATOMS
