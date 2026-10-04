"""Celery tasks — thin wrappers around domain/media services."""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path

from celery import shared_task
from django.conf import settings

from apps.core.storage import get_storage
from apps.processing.media import (
    MediaPipelineError,
    cut_segment_audio,
    download_source_audio,
    fetch_source_metadata as extract_metadata,
    sha256_file,
)
from apps.processing.models import SourceMediaCache
from apps.processing.services.job import JobService
from apps.workspace.models import VideoSource
from apps.workspace.services.source import SourceService

logger = logging.getLogger(__name__)


@shared_task(name="youaudiolab.fetch_source_metadata", bind=True, max_retries=0)
def fetch_source_metadata(self, source_id: str) -> dict[str, str]:
    service = SourceService()
    sid = uuid.UUID(source_id)
    try:
        source = service.get(sid)
        info = extract_metadata(
            youtube_url=source.youtube_url,
            cookies_file=settings.YTDLP_COOKIES_FILE,
        )
        service.apply_metadata_result(
            sid,
            success=True,
            title=info.get("title"),
            channel_name=info.get("channel_name"),
            duration_seconds=info.get("duration_seconds"),
            metadata_json=info.get("metadata_json"),
        )
        return {"source_id": source_id, "status": "READY"}
    except MediaPipelineError as exc:
        logger.warning("metadata fetch failed for %s: %s", source_id, exc.message)
        service.apply_metadata_result(
            sid,
            success=False,
            metadata_json={"error": exc.message},
        )
        return {"source_id": source_id, "status": "METADATA_FAILED"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("fetch_source_metadata failed for %s", source_id)
        try:
            service.apply_metadata_result(
                sid,
                success=False,
                metadata_json={"error": str(exc)[:2000]},
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to mark source %s METADATA_FAILED", source_id)
        return {"source_id": source_id, "status": "METADATA_FAILED"}


@shared_task(name="youaudiolab.extract_segment_audio", bind=True, max_retries=0)
def extract_segment_audio(self, job_id: str) -> dict[str, str]:
    jid = uuid.UUID(job_id)
    storage = get_storage()
    jobs = JobService(storage)

    try:
        job = jobs.mark_running(jid)
        if job.status == "CANCELLED":
            return {"job_id": job_id, "status": "CANCELLED"}

        source = VideoSource.objects.filter(pk=job.source_id).first()
        if source is None:
            jobs.fail(jid, error_code="SOURCE_MISSING", error_message="Source not found")
            return {"job_id": job_id, "status": "FAILED"}

        cache_rel = f"cache/sources/{source.id}/{source.youtube_video_id}"
        cache_dir = Path(settings.STORAGE_ROOT) / "cache" / "sources" / str(source.id)
        cache_dir.mkdir(parents=True, exist_ok=True)

        media_cache = SourceMediaCache.objects.filter(source_id=source.id).first()
        src_path: Path | None = None
        if media_cache is not None:
            candidate = Path(settings.STORAGE_ROOT) / media_cache.storage_key
            if candidate.is_file() and candidate.stat().st_size > 0:
                src_path = candidate

        if src_path is None:
            try:
                downloaded = download_source_audio(
                    youtube_url=source.youtube_url,
                    video_id=source.youtube_video_id,
                    cache_dir=cache_dir,
                    cookies_file=settings.YTDLP_COOKIES_FILE,
                )
            except MediaPipelineError as exc:
                jobs.fail(jid, error_code=exc.code, error_message=exc.message)
                return {"job_id": job_id, "status": "FAILED"}

            ext = downloaded.suffix or ".m4a"
            storage_key = f"{cache_rel}{ext}"
            dest_cache = Path(settings.STORAGE_ROOT) / storage_key
            dest_cache.parent.mkdir(parents=True, exist_ok=True)
            if downloaded.resolve() != dest_cache.resolve():
                shutil.copy2(downloaded, dest_cache)
            src_path = dest_cache

            source_checksum = sha256_file(src_path)
            source_size = src_path.stat().st_size
            if media_cache is None:
                media_cache = SourceMediaCache.objects.create(
                    source=source,
                    storage_key=storage_key,
                    file_size_bytes=source_size,
                    checksum=source_checksum,
                )
            else:
                media_cache.storage_key = storage_key
                media_cache.file_size_bytes = source_size
                media_cache.checksum = source_checksum
                media_cache.save(
                    update_fields=[
                        "storage_key",
                        "file_size_bytes",
                        "checksum",
                        "updated_at",
                    ]
                )
        else:
            source_checksum = sha256_file(src_path)
            source_size = src_path.stat().st_size
            storage_key = media_cache.storage_key
            if (
                media_cache.checksum != source_checksum
                or media_cache.file_size_bytes != source_size
            ):
                media_cache.checksum = source_checksum
                media_cache.file_size_bytes = source_size
                media_cache.save(
                    update_fields=["checksum", "file_size_bytes", "updated_at"]
                )

        ytdlp_version = None
        try:
            import yt_dlp

            ytdlp_version = getattr(yt_dlp, "version", None)
            if ytdlp_version is not None:
                ytdlp_version = getattr(ytdlp_version, "__version__", None) or str(
                    ytdlp_version
                )
        except Exception:  # noqa: BLE001
            ytdlp_version = None

        # Pin the exact source bytes used for this extract (video_id alone is not enough).
        snap = dict(job.config_snapshot or {})
        snap["source_storage_key"] = storage_key
        snap["source_checksum"] = source_checksum
        snap["source_file_size_bytes"] = source_size
        if ytdlp_version:
            snap["ytdlp_version"] = ytdlp_version
        job.config_snapshot = snap
        job.save(update_fields=["config_snapshot"])

        artifact_key = (
            f"projects/{job.project_id}/segments/{job.segment_id}/"
            f"jobs/{job.id}/audio.wav"
        )

        try:
            with tempfile.TemporaryDirectory(prefix="yal-cut-") as tmp:
                tmp_out = Path(tmp) / "segment.wav"
                cut_segment_audio(
                    src=src_path,
                    dest=tmp_out,
                    start_seconds=job.start_seconds,
                    end_seconds=job.end_seconds,
                    config_snapshot=job.config_snapshot or {},
                    ffmpeg_bin=settings.FFMPEG_BIN,
                    timeout=settings.FFMPEG_TIMEOUT_SECONDS,
                )
                data = tmp_out.read_bytes()
                storage.put(artifact_key, data)
                checksum = sha256_file(tmp_out)
        except MediaPipelineError as exc:
            jobs.fail(jid, error_code=exc.code, error_message=exc.message)
            return {"job_id": job_id, "status": "FAILED"}

        result = jobs.publish(
            jid,
            storage_key=artifact_key,
            file_size_bytes=len(data),
            checksum=checksum,
        )
        return {"job_id": job_id, "status": result.status}
    except Exception as exc:  # noqa: BLE001
        logger.exception("extract_segment_audio failed for %s", job_id)
        try:
            jobs.fail(
                jid,
                error_code="WORKER_ERROR",
                error_message=str(exc)[:2000],
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to mark job %s as FAILED", job_id)
        return {"job_id": job_id, "status": "FAILED"}

@shared_task(name="youaudiolab.transcribe_segment_audio", bind=True, max_retries=0)
def transcribe_segment_audio(self, job_id: str) -> dict[str, str]:
    from apps.processing.services.asr import AsrService

    jid = uuid.UUID(job_id)
    asr = AsrService(get_storage())
    try:
        result = asr.complete_asr(jid)
        return {"job_id": job_id, "status": result.status}
    except Exception as exc:  # noqa: BLE001
        logger.exception("transcribe_segment_audio failed for %s", job_id)
        try:
            JobService(get_storage()).fail(
                jid,
                error_code="WORKER_ERROR",
                error_message=str(exc)[:2000],
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to mark ASR job %s as FAILED", job_id)
        return {"job_id": job_id, "status": "FAILED"}
