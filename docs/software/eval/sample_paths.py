"""Resolve redistributable sample audio paths (no machine-local absolute paths in CSV)."""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def default_audio_root() -> Path | None:
    raw = (os.environ.get("YOUAUDIOLAB_AUDIO_ROOT") or "").strip()
    return Path(raw) if raw else None


def canonical_watch_url(video_id: str, url: str = "") -> str:
    vid = (video_id or "").strip()
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    raw = (url or "").strip()
    if "watch?v=" in raw:
        part = raw.split("watch?v=", 1)[1]
        vid = part.split("&", 1)[0].split("#", 1)[0]
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"
    return raw


def audio_relpath_for(segment_id: str) -> str:
    return f"audio/{segment_id}.mp3"


def resolve_audio_path(
    row: dict[str, str],
    *,
    audio_root: Path | None = None,
) -> Path:
    """Resolve a sample row to a local MP3 path.

    Prefers ``audio_relpath`` (redistributable). Falls back to legacy ``audio_path``.
    Relative entries are resolved under ``audio_root`` or env ``YOUAUDIOLAB_AUDIO_ROOT``.
    """
    rel = (row.get("audio_relpath") or "").strip()
    legacy = (row.get("audio_path") or "").strip()
    candidate = Path(rel or legacy)
    if candidate.is_file():
        return candidate

    root = Path(audio_root) if audio_root is not None else default_audio_root()
    if root is not None:
        if candidate.name:
            under_root = root / candidate.name
            if under_root.is_file():
                return under_root
            nested = root / candidate
            if nested.is_file():
                return nested
        return root / (candidate.name or f"{row.get('segment_id', 'unknown')}.mp3")

    if legacy:
        legacy_path = Path(legacy)
        if legacy_path.is_file():
            return legacy_path

    return candidate if candidate.parts else Path(f"{row.get('segment_id', 'unknown')}.mp3")
