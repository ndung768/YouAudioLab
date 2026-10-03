"""Enqueue helpers — call after DB commit so workers see the row."""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


def enqueue_extract_segment_audio(job_id: uuid.UUID) -> None:
    def _send() -> None:
        if not settings.CELERY_ENQUEUE_ENABLED:
            logger.info("Celery enqueue disabled; job %s left QUEUED", job_id)
            return
        from apps.processing.tasks import extract_segment_audio

        extract_segment_audio.delay(str(job_id))
        logger.info("Enqueued extract_segment_audio for job %s", job_id)

    transaction.on_commit(_send)


def enqueue_fetch_source_metadata(source_id: uuid.UUID) -> None:
    def _send() -> None:
        if not settings.CELERY_ENQUEUE_ENABLED:
            logger.info("Celery enqueue disabled; metadata for %s not fetched", source_id)
            return
        from apps.processing.tasks import fetch_source_metadata

        fetch_source_metadata.delay(str(source_id))
        logger.info("Enqueued fetch_source_metadata for source %s", source_id)

    transaction.on_commit(_send)


def enqueue_transcribe_segment_audio(job_id: uuid.UUID) -> None:
    def _send() -> None:
        if not settings.CELERY_ENQUEUE_ENABLED:
            logger.info("Celery enqueue disabled; ASR job %s left QUEUED", job_id)
            return
        from apps.processing.tasks import transcribe_segment_audio

        transcribe_segment_audio.delay(str(job_id))
        logger.info("Enqueued transcribe_segment_audio for job %s", job_id)

    transaction.on_commit(_send)
