"""YouTube URL parsing helpers."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from apps.core.errors import ValidationError

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_youtube_video_id(youtube_url: str) -> str:
    """Extract an 11-char YouTube video id from common URL forms."""
    raw = (youtube_url or "").strip()
    if not raw:
        raise ValidationError(
            "youtube_url is required",
            details={"fields": [{"field": "youtube_url", "code": "REQUIRED"}]},
        )

    if _VIDEO_ID_RE.match(raw):
        return raw

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()

    if host in {"youtu.be"}:
        candidate = parsed.path.lstrip("/").split("/")[0]
        return _require_valid_id(candidate)

    if "youtube.com" in host or host == "m.youtube.com":
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return _require_valid_id(qs["v"][0])

        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live", "v"}:
            return _require_valid_id(parts[1])

    raise ValidationError(
        "Could not parse YouTube video id from URL",
        details={"fields": [{"field": "youtube_url", "code": "INVALID_YOUTUBE_URL"}]},
    )


def _require_valid_id(candidate: str) -> str:
    candidate = candidate.strip()
    if not _VIDEO_ID_RE.match(candidate):
        raise ValidationError(
            "Invalid YouTube video id",
            details={"fields": [{"field": "youtube_url", "code": "INVALID_YOUTUBE_ID"}]},
        )
    return candidate
