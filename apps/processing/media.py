"""yt-dlp download + FFmpeg cut helpers. Commands use argument arrays only."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from django.conf import settings


class MediaPipelineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def find_cached_file(cache_dir: Path, video_id: str) -> Path | None:
    for ext in (".m4a", ".webm", ".opus", ".mp3", ".wav", ".ogg"):
        candidate = cache_dir / f"{video_id}{ext}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    matches = [
        p
        for p in cache_dir.glob(f"{video_id}.*")
        if p.is_file() and p.suffix.lower() not in {".part", ".ytdl"}
    ]
    return matches[0] if matches else None


def fetch_source_metadata(
    *,
    youtube_url: str,
    cookies_file: str | None = None,
) -> dict[str, Any]:
    """Extract title/channel/duration without downloading media."""
    import yt_dlp

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "socket_timeout": settings.YTDLP_SOCKET_TIMEOUT,
    }
    if cookies_file:
        opts["cookiefile"] = cookies_file
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
    except Exception as exc:  # noqa: BLE001
        raise MediaPipelineError("YTDLP_METADATA_FAILED", str(exc)) from exc
    if not info:
        raise MediaPipelineError("YTDLP_METADATA_FAILED", "No metadata returned")
    duration = info.get("duration")
    description = info.get("description") or ""
    if not isinstance(description, str):
        description = str(description)
    return {
        "title": info.get("title"),
        "channel_name": info.get("channel") or info.get("uploader"),
        "duration_seconds": float(duration) if duration is not None else None,
        "metadata_json": {
            "id": info.get("id"),
            "title": info.get("title"),
            "channel": info.get("channel") or info.get("uploader"),
            "duration": duration,
            "webpage_url": info.get("webpage_url"),
            "description": description,
        },
    }


def download_source_audio(
    *,
    youtube_url: str,
    video_id: str,
    cache_dir: Path,
    cookies_file: str | None = None,
) -> Path:
    import yt_dlp

    cache_dir.mkdir(parents=True, exist_ok=True)
    existing = find_cached_file(cache_dir, video_id)
    if existing is not None:
        return existing

    outtmpl = str(cache_dir / f"{video_id}.%(ext)s")
    opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "ignoreerrors": False,
        "socket_timeout": settings.YTDLP_SOCKET_TIMEOUT,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ],
    }
    if cookies_file:
        opts["cookiefile"] = cookies_file

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([youtube_url])
    except Exception as exc:  # noqa: BLE001
        raise MediaPipelineError("YTDLP_DOWNLOAD_FAILED", str(exc)) from exc

    path = find_cached_file(cache_dir, video_id)
    if path is None:
        raise MediaPipelineError(
            "YTDLP_DOWNLOAD_FAILED",
            "File not found after yt-dlp download",
        )
    return path


def build_ffmpeg_cut_command(
    *,
    ffmpeg_bin: str,
    src: Path,
    dest: Path,
    start_seconds: float,
    end_seconds: float,
    config_snapshot: dict[str, Any],
) -> list[str]:
    sample_rate = int(config_snapshot.get("sample_rate_hz", 16000))
    channels = int(config_snapshot.get("channels", 1))
    loudness = bool(config_snapshot.get("loudness_normalization", False))

    cmd: list[str] = [
        ffmpeg_bin,
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-to",
        f"{end_seconds:.3f}",
        "-i",
        str(src),
        "-vn",
    ]
    if loudness:
        cmd.extend(["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"])
    cmd.extend(
        [
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            str(dest),
        ]
    )
    return cmd


def cut_segment_audio(
    *,
    src: Path,
    dest: Path,
    start_seconds: float,
    end_seconds: float,
    config_snapshot: dict[str, Any],
    ffmpeg_bin: str = "ffmpeg",
    timeout: int | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_cut_command(
        ffmpeg_bin=ffmpeg_bin,
        src=src,
        dest=dest,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        config_snapshot=config_snapshot,
    )
    try:
        proc = subprocess.run(  # noqa: S603 — explicit argument array, no shell
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaPipelineError("FFMPEG_TIMEOUT", str(exc)) from exc
    except OSError as exc:
        raise MediaPipelineError("FFMPEG_MISSING", str(exc)) from exc

    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        raise MediaPipelineError("FFMPEG_CUT_FAILED", err[-1000:])
    return dest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
