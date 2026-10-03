"""ProcessingJob domain service — submit, cancel, retry, publish."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from django.db import IntegrityError, transaction

from apps.core.errors import (
    ActiveJobExistsError,
    InvalidStateTransitionError,
    NotFoundError,
    SegmentDeletedError,
    SegmentRevisionConflictError,
    ValidationError,
)
from apps.core.storage import StoragePort
from apps.processing.models import ProcessingArtifact, ProcessingJob
from apps.workspace.models import AudioSegment, ProjectSettings, VideoSource
from apps.workspace.services.membership import MembershipService

_ACTIVE = {ProcessingJob.Status.QUEUED, ProcessingJob.Status.RUNNING}
_TERMINAL = {
    ProcessingJob.Status.SUCCEEDED,
    ProcessingJob.Status.FAILED,
    ProcessingJob.Status.STALE,
    ProcessingJob.Status.CANCELLED,
}


class JobService:
    def __init__(self, storage: StoragePort) -> None:
        self.storage = storage
        self.memberships = MembershipService()

    def get(self, job_id: uuid.UUID) -> ProcessingJob:
        try:
            return ProcessingJob.objects.get(pk=job_id)
        except ProcessingJob.DoesNotExist as exc:
            raise NotFoundError("Job not found", details={"job_id": str(job_id)}) from exc

    def get_artifact(self, artifact_id: uuid.UUID) -> ProcessingArtifact:
        try:
            return ProcessingArtifact.objects.get(pk=artifact_id)
        except ProcessingArtifact.DoesNotExist as exc:
            raise NotFoundError(
                "Artifact not found",
                details={"artifact_id": str(artifact_id)},
            ) from exc

    def list_for_segment(self, segment_id: uuid.UUID) -> list[ProcessingJob]:
        return list(
            ProcessingJob.objects.filter(segment_id=segment_id).order_by("-created_at")
        )

    def list_for_project(self, project_id: uuid.UUID) -> list[ProcessingJob]:
        return list(
            ProcessingJob.objects.filter(project_id=project_id).order_by("-created_at")
        )

    def _load_segment_context(
        self,
        segment_id: uuid.UUID,
    ) -> tuple[AudioSegment, VideoSource, ProjectSettings]:
        try:
            segment = AudioSegment.objects.select_related("source").get(pk=segment_id)
        except AudioSegment.DoesNotExist as exc:
            raise NotFoundError(
                "Segment not found",
                details={"segment_id": str(segment_id)},
            ) from exc
        source = segment.source
        try:
            settings = ProjectSettings.objects.get(pk=source.project_id)
        except ProjectSettings.DoesNotExist as exc:
            raise NotFoundError(
                "Project settings not found",
                details={"project_id": str(source.project_id)},
            ) from exc
        return segment, source, settings

    def _find_active(
        self,
        segment_id: uuid.UUID,
        expected_revision: int,
        job_type: str = ProcessingJob.JobType.EXTRACT_SEGMENT_AUDIO,
    ) -> ProcessingJob | None:
        return ProcessingJob.objects.filter(
            segment_id=segment_id,
            expected_revision=expected_revision,
            job_type=job_type,
            status__in=list(_ACTIVE),
        ).first()

    def _config_snapshot(self, settings: ProjectSettings) -> dict[str, Any]:
        return {
            "output_format": settings.output_format,
            "encoding": settings.encoding,
            "sample_rate_hz": settings.sample_rate_hz,
            "channels": settings.channels,
            "loudness_normalization": settings.loudness_normalization,
        }

    def submit(
        self,
        *,
        segment_id: uuid.UUID,
        expected_definition_revision: int,
        actor_user_id: uuid.UUID,
        idempotency_key: str | None = None,
    ) -> ProcessingJob:
        if expected_definition_revision is None:
            raise ValidationError(
                "expected_definition_revision is required",
                details={
                    "fields": [
                        {
                            "field": "expected_definition_revision",
                            "code": "REQUIRED",
                        }
                    ]
                },
            )

        segment, source, settings = self._load_segment_context(segment_id)
        self.memberships.require_owner(source.project_id, actor_user_id)
        self.memberships.require_active_project(source.project_id)

        if segment.deleted_at is not None:
            raise SegmentDeletedError(
                "Segment is soft-deleted",
                details={"segment_id": str(segment_id)},
            )
        if segment.definition_revision != expected_definition_revision:
            raise SegmentRevisionConflictError(
                "Segment definition_revision conflict",
                details={
                    "segment_id": str(segment_id),
                    "current_definition_revision": segment.definition_revision,
                    "expected_definition_revision": expected_definition_revision,
                },
            )

        existing = self._find_active(
            segment_id,
            expected_definition_revision,
            ProcessingJob.JobType.EXTRACT_SEGMENT_AUDIO,
        )
        if existing is not None:
            raise ActiveJobExistsError(
                "Active job already exists for this segment revision",
                details={
                    "job_id": str(existing.id),
                    "segment_id": str(segment_id),
                    "expected_revision": expected_definition_revision,
                },
            )

        try:
            with transaction.atomic():
                job = ProcessingJob.objects.create(
                    segment=segment,
                    source=source,
                    project_id=source.project_id,
                    expected_revision=segment.definition_revision,
                    job_type=ProcessingJob.JobType.EXTRACT_SEGMENT_AUDIO,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    config_snapshot=self._config_snapshot(settings),
                    idempotency_key=idempotency_key,
                    status=ProcessingJob.Status.QUEUED,
                    attempt_n=1,
                )
        except IntegrityError as exc:
            active = self._find_active(
                segment_id,
                expected_definition_revision,
                ProcessingJob.JobType.EXTRACT_SEGMENT_AUDIO,
            )
            raise ActiveJobExistsError(
                "Active job already exists for this segment revision",
                details={
                    "job_id": str(active.id) if active else None,
                    "segment_id": str(segment_id),
                    "expected_revision": expected_definition_revision,
                },
            ) from exc

        segment.processing_status = AudioSegment.ProcessingStatus.PROCESSING
        segment.current_job = job
        segment.save(update_fields=["processing_status", "current_job", "updated_at"])
        return job

    def _lock_segment_then_job(
        self, job_id: uuid.UUID
    ) -> tuple[AudioSegment, ProcessingJob]:
        peek = ProcessingJob.objects.filter(pk=job_id).first()
        if peek is None:
            raise NotFoundError("Job not found", details={"job_id": str(job_id)})

        try:
            segment = AudioSegment.objects.select_for_update().get(pk=peek.segment_id)
        except AudioSegment.DoesNotExist as exc:
            raise NotFoundError(
                "Segment not found",
                details={"segment_id": str(peek.segment_id)},
            ) from exc

        try:
            job = ProcessingJob.objects.select_for_update().get(pk=job_id)
        except ProcessingJob.DoesNotExist as exc:
            raise NotFoundError("Job not found", details={"job_id": str(job_id)}) from exc
        return segment, job

    def mark_running(self, job_id: uuid.UUID) -> ProcessingJob:
        with transaction.atomic():
            segment, job = self._lock_segment_then_job(job_id)
            if job.status == ProcessingJob.Status.RUNNING:
                return job
            if job.status != ProcessingJob.Status.QUEUED:
                raise InvalidStateTransitionError(
                    "Only QUEUED jobs can start",
                    details={"job_id": str(job_id), "status": job.status},
                )
            if job.cancel_requested_at is not None:
                job.status = ProcessingJob.Status.CANCELLED
                job.finished_at = datetime.now(timezone.utc)
                job.save(update_fields=["status", "finished_at"])
                if segment.current_job_id == job.id:
                    segment.current_job = None
                    segment.save(update_fields=["current_job", "updated_at"])
                return job

            job.status = ProcessingJob.Status.RUNNING
            job.started_at = datetime.now(timezone.utc)
            job.save(update_fields=["status", "started_at"])
            return job

    def cancel(self, job_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> ProcessingJob:
        with transaction.atomic():
            segment, job = self._lock_segment_then_job(job_id)
            self.memberships.require_owner(job.project_id, actor_user_id)
            self.memberships.require_active_project(job.project_id)

            if job.status == ProcessingJob.Status.CANCELLED:
                return job

            if job.status in {
                ProcessingJob.Status.SUCCEEDED,
                ProcessingJob.Status.FAILED,
                ProcessingJob.Status.STALE,
            }:
                raise InvalidStateTransitionError(
                    "Cannot cancel a terminal job",
                    details={"job_id": str(job_id), "status": job.status},
                )

            if job.cancel_requested_at is None:
                job.cancel_requested_at = datetime.now(timezone.utc)

            if job.status == ProcessingJob.Status.QUEUED:
                job.status = ProcessingJob.Status.CANCELLED
                job.finished_at = datetime.now(timezone.utc)
                if job.job_type == ProcessingJob.JobType.TRANSCRIBE_SEGMENT_AUDIO:
                    if segment.current_asr_job_id == job.id:
                        segment.current_asr_job = None
                        segment.save(update_fields=["current_asr_job", "updated_at"])
                else:
                    if segment.current_job_id == job.id:
                        segment.current_job = None
                    if segment.processing_status == AudioSegment.ProcessingStatus.PROCESSING:
                        segment.processing_status = AudioSegment.ProcessingStatus.PENDING
                    segment.save()

            job.save()
            return job

    def retry(
        self,
        job_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        idempotency_key: str | None = None,
    ) -> ProcessingJob:
        old = self.get(job_id)
        self.memberships.require_owner(old.project_id, actor_user_id)
        self.memberships.require_active_project(old.project_id)

        if old.status in _ACTIVE:
            raise InvalidStateTransitionError(
                "Cannot retry an active job",
                details={"job_id": str(job_id), "status": old.status},
            )

        segment, source, settings = self._load_segment_context(old.segment_id)
        if segment.deleted_at is not None:
            raise SegmentDeletedError(
                "Segment is soft-deleted",
                details={"segment_id": str(segment.id)},
            )
        if segment.definition_revision != old.expected_revision:
            raise SegmentRevisionConflictError(
                "Segment revision moved; cannot retry obsolete job",
                details={
                    "job_id": str(job_id),
                    "job_expected_revision": old.expected_revision,
                    "current_definition_revision": segment.definition_revision,
                },
            )

        existing = self._find_active(segment.id, old.expected_revision, old.job_type)
        if existing is not None:
            raise ActiveJobExistsError(
                "Active job already exists for this segment revision",
                details={
                    "job_id": str(existing.id),
                    "segment_id": str(segment.id),
                    "expected_revision": old.expected_revision,
                },
            )

        snap = dict(old.config_snapshot or {})
        if old.job_type == ProcessingJob.JobType.TRANSCRIBE_SEGMENT_AUDIO:
            if segment.current_artifact_id is None:
                from apps.core.errors import ArtifactRequiredError

                raise ArtifactRequiredError(
                    "Segment has no current verified audio artifact",
                    details={"segment_id": str(segment.id)},
                )
            snap["artifact_id"] = str(segment.current_artifact_id)
            art = ProcessingArtifact.objects.filter(pk=segment.current_artifact_id).first()
            if art is not None:
                snap["artifact_checksum"] = art.checksum
        else:
            snap = self._config_snapshot(settings)

        try:
            with transaction.atomic():
                new_job = ProcessingJob.objects.create(
                    segment=segment,
                    source=source,
                    project_id=source.project_id,
                    expected_revision=old.expected_revision,
                    job_type=old.job_type,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    config_snapshot=snap,
                    idempotency_key=idempotency_key,
                    status=ProcessingJob.Status.QUEUED,
                    attempt_n=old.attempt_n + 1,
                    retry_of=old,
                )
                if old.job_type == ProcessingJob.JobType.TRANSCRIBE_SEGMENT_AUDIO:
                    segment.current_asr_job = new_job
                    segment.save(update_fields=["current_asr_job", "updated_at"])
                else:
                    segment.processing_status = AudioSegment.ProcessingStatus.PROCESSING
                    segment.current_job = new_job
                    segment.save(
                        update_fields=["processing_status", "current_job", "updated_at"]
                    )
                return new_job
        except IntegrityError as exc:
            active = self._find_active(segment.id, old.expected_revision, old.job_type)
            raise ActiveJobExistsError(
                "Active job already exists for this segment revision",
                details={"job_id": str(active.id) if active else None},
            ) from exc

    def fail(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        error_message: str,
    ) -> ProcessingJob:
        with transaction.atomic():
            segment, job = self._lock_segment_then_job(job_id)
            if job.status in _TERMINAL:
                raise InvalidStateTransitionError(
                    "Job already terminal",
                    details={"job_id": str(job_id), "status": job.status},
                )
            job.status = ProcessingJob.Status.FAILED
            job.error_code = error_code
            job.error_message = error_message
            job.finished_at = datetime.now(timezone.utc)
            job.save()
            if job.job_type == ProcessingJob.JobType.TRANSCRIBE_SEGMENT_AUDIO:
                if segment.current_asr_job_id == job.id:
                    segment.current_asr_job = None
                    segment.save(update_fields=["current_asr_job", "updated_at"])
                return job
            if segment.current_job_id == job.id:
                segment.current_job = None
            segment.processing_status = AudioSegment.ProcessingStatus.FAILED
            segment.save()
            return job

    def publish(
        self,
        job_id: uuid.UUID,
        *,
        storage_key: str,
        file_size_bytes: int | None = None,
        checksum: str | None = None,
    ) -> ProcessingJob:
        """Publish only when expected_revision still matches and segment is live."""
        with transaction.atomic():
            segment, job = self._lock_segment_then_job(job_id)

            if job.status in _TERMINAL:
                raise InvalidStateTransitionError(
                    "Job already terminal",
                    details={"job_id": str(job_id), "status": job.status},
                )

            now = datetime.now(timezone.utc)

            if (
                segment.deleted_at is not None
                or segment.definition_revision != job.expected_revision
            ):
                job.status = ProcessingJob.Status.STALE
                job.finished_at = now
                job.save(update_fields=["status", "finished_at"])
                self._clear_segment_current_job_if_matches(segment, job)
                return job

            if job.cancel_requested_at is not None:
                job.status = ProcessingJob.Status.CANCELLED
                job.finished_at = now
                job.save(update_fields=["status", "finished_at"])
                self._clear_segment_current_job_if_matches(segment, job)
                if segment.processing_status == AudioSegment.ProcessingStatus.PROCESSING:
                    segment.processing_status = AudioSegment.ProcessingStatus.PENDING
                    segment.save(update_fields=["processing_status", "updated_at"])
                return job

            if not self.storage.exists(storage_key):
                job.status = ProcessingJob.Status.FAILED
                job.error_code = "ARTIFACT_MISSING"
                job.error_message = f"storage_key not found: {storage_key}"
                job.finished_at = now
                job.save()
                segment.processing_status = AudioSegment.ProcessingStatus.FAILED
                self._clear_segment_current_job_if_matches(segment, job)
                segment.save()
                return job

            data = self.storage.get(storage_key)
            size = file_size_bytes if file_size_bytes is not None else len(data)
            digest = checksum or hashlib.sha256(data).hexdigest()
            snap = job.config_snapshot or {}
            artifact = ProcessingArtifact.objects.create(
                job=job,
                storage_key=storage_key,
                format=str(snap.get("output_format", "WAV")),
                sample_rate_hz=int(snap.get("sample_rate_hz", 16000)),
                channels=int(snap.get("channels", 1)),
                file_size_bytes=size,
                checksum=digest,
                verified=True,
            )

            job.status = ProcessingJob.Status.SUCCEEDED
            job.finished_at = now
            job.error_code = None
            job.error_message = None
            job.save()

            segment.current_job = job
            segment.current_artifact = artifact
            segment.processing_status = AudioSegment.ProcessingStatus.COMPLETED
            segment.save()
            return job

    def simulate_worker_success(
        self,
        job_id: uuid.UUID,
        *,
        payload: bytes = b"FAKE_WAV_BYTES",
    ) -> ProcessingJob:
        job = self.mark_running(job_id)
        if job.status == ProcessingJob.Status.CANCELLED:
            return job
        storage_key = (
            f"projects/{job.project_id}/segments/{job.segment_id}/"
            f"jobs/{job.id}/audio.wav"
        )
        self.storage.put(storage_key, payload)
        return self.publish(job.id, storage_key=storage_key)

    def _clear_segment_current_job_if_matches(
        self,
        segment: AudioSegment,
        job: ProcessingJob,
    ) -> None:
        if segment.current_job_id == job.id:
            segment.current_job = None
            segment.save(update_fields=["current_job", "updated_at"])
