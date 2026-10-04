"""ASR domain service — submit / complete / apply (W2–W5; fake engine default)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.core.errors import (
    ActiveJobExistsError,
    ArtifactNotVerifiedError,
    ArtifactRequiredError,
    AsrLimitExceededError,
    AsrProviderMisconfiguredError,
    AsrRunNotCurrentError,
    InvalidStateTransitionError,
    NotFoundError,
    SegmentDeletedError,
    SegmentRevisionConflictError,
    ValidationError,
)
from apps.core.storage import StoragePort
from apps.processing.models import AsrRun, ProcessingArtifact, ProcessingJob
from apps.processing.services.asr_engine import (
    AsrEngine,
    AsrEngineConfig,
    AsrEngineError,
    AsrEngineResult,
    build_asr_engine,
)
from apps.processing.services.asr_resolve import resolve_asr_config, resolve_runtime_api_key
from apps.workspace.models import AudioSegment, Project, VideoSource
from apps.workspace.services.membership import MembershipService
from apps.workspace.services.project import ProjectService

_ACTIVE = {ProcessingJob.Status.QUEUED, ProcessingJob.Status.RUNNING}
_TERMINAL = {
    ProcessingJob.Status.SUCCEEDED,
    ProcessingJob.Status.FAILED,
    ProcessingJob.Status.STALE,
    ProcessingJob.Status.CANCELLED,
}
_ASR_TYPE = ProcessingJob.JobType.TRANSCRIBE_SEGMENT_AUDIO


class AsrService:
    def __init__(
        self,
        storage: StoragePort,
        engine: AsrEngine | None = None,
    ) -> None:
        self.storage = storage
        self.memberships = MembershipService()
        self._engine_override = engine

    @property
    def engine(self) -> AsrEngine:
        if self._engine_override is not None:
            return self._engine_override
        return build_asr_engine(
            engine_name=getattr(settings, "ASR_ENGINE", "fake"),
            model_cache_dir=getattr(settings, "ASR_MODEL_CACHE_DIR", "./storage/whisper-models"),
            download=getattr(settings, "ASR_DOWNLOAD_MODELS", True),
        )

    def get_run(self, asr_run_id: uuid.UUID) -> AsrRun:
        try:
            return AsrRun.objects.get(pk=asr_run_id)
        except AsrRun.DoesNotExist as exc:
            raise NotFoundError(
                "ASR run not found",
                details={"asr_run_id": str(asr_run_id)},
            ) from exc

    def list_runs_for_segment(
        self, segment_id: uuid.UUID, *, actor_user_id: uuid.UUID
    ) -> list[AsrRun]:
        segment = AudioSegment.objects.select_related("source").get(pk=segment_id)
        if segment.deleted_at is not None:
            raise NotFoundError("Segment not found", details={"segment_id": str(segment_id)})
        self.memberships.require_member(segment.source.project_id, actor_user_id)
        return list(
            AsrRun.objects.filter(segment_id=segment_id).order_by("-created_at")
        )

    def list_asr_jobs_for_segment(
        self, segment_id: uuid.UUID, *, actor_user_id: uuid.UUID
    ) -> list[ProcessingJob]:
        segment = AudioSegment.objects.select_related("source").get(pk=segment_id)
        if segment.deleted_at is not None:
            raise NotFoundError("Segment not found", details={"segment_id": str(segment_id)})
        self.memberships.require_member(segment.source.project_id, actor_user_id)
        return list(
            ProcessingJob.objects.filter(
                segment_id=segment_id,
                job_type=_ASR_TYPE,
            ).order_by("-created_at")
        )

    def submit(
        self,
        *,
        segment_id: uuid.UUID,
        expected_definition_revision: int,
        actor_user_id: uuid.UUID,
        language: str | None = None,
        model_size: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        force: bool = False,
        idempotency_key: str | None = None,
    ) -> tuple[ProcessingJob, bool]:
        if expected_definition_revision is None:
            raise ValidationError(
                "expected_definition_revision is required",
                details={
                    "fields": [
                        {"field": "expected_definition_revision", "code": "REQUIRED"}
                    ]
                },
            )

        segment, source, project, artifact = self._load_asr_context(segment_id)
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

        language_requested = (language or project.language or "vi").strip() or "vi"
        if len(language_requested) > 16:
            raise ValidationError(
                "language too long",
                details={"fields": [{"field": "language", "code": "TOO_LONG"}]},
            )

        max_dur = float(getattr(settings, "ASR_MAX_DURATION_SECONDS", 1800))
        if segment.duration_seconds > max_dur:
            raise AsrLimitExceededError(
                "Segment duration exceeds ASR limit",
                details={
                    "duration_seconds": segment.duration_seconds,
                    "max_duration_seconds": max_dur,
                },
            )

        override_provider = provider.strip().lower() if provider else None
        override_model = (model or model_size or None)
        if override_model is not None:
            override_model = override_model.strip() or None

        resolved = resolve_asr_config(
            actor_user_id=actor_user_id,
            language_requested=language_requested,
            override_provider=override_provider,
            override_model=override_model,
            project_id=source.project_id,
        )

        config_snapshot = {
            "artifact_id": str(artifact.id),
            "artifact_checksum": artifact.checksum,
            "provider": resolved.provider,
            "engine": resolved.engine,
            "model": resolved.model,
            "model_name": resolved.model_name,
            "model_size": resolved.model_size,
            "language_requested": resolved.language_requested,
            "task": resolved.task,
            "actor_user_id": str(resolved.actor_user_id),
            "job_override": resolved.job_override,
            "limits": {
                "max_duration_seconds": max_dur,
                "timeout_seconds": int(getattr(settings, "ASR_TIMEOUT_SECONDS", 600)),
            },
        }
        if resolved.provider == "local":
            config_snapshot["device"] = resolved.device
            config_snapshot["compute_type"] = resolved.compute_type
            config_snapshot["decode_params"] = dict(resolved.decode_params or {})
        else:
            config_snapshot["device"] = None
            config_snapshot["compute_type"] = None
            config_snapshot["decode_params"] = {}
            config_snapshot["openai_base_url"] = resolved.openai_base_url

        if not force:
            reused = self._find_equivalent_succeeded(
                segment_id=segment.id,
                segment_revision=segment.definition_revision,
                artifact=artifact,
                language_requested=language_requested,
                model=resolved.model,
                engine=resolved.engine,
                provider=resolved.provider,
            )
            if reused is not None:
                return reused, False

        existing = ProcessingJob.objects.filter(
            segment_id=segment.id,
            expected_revision=segment.definition_revision,
            job_type=_ASR_TYPE,
            status__in=list(_ACTIVE),
        ).first()
        if existing is not None:
            raise ActiveJobExistsError(
                "Active ASR job already exists for this segment revision",
                details={
                    "job_id": str(existing.id),
                    "segment_id": str(segment_id),
                    "job_type": _ASR_TYPE,
                },
            )

        try:
            with transaction.atomic():
                job = ProcessingJob.objects.create(
                    segment=segment,
                    source=source,
                    project_id=source.project_id,
                    expected_revision=segment.definition_revision,
                    job_type=_ASR_TYPE,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    config_snapshot=config_snapshot,
                    idempotency_key=idempotency_key,
                    status=ProcessingJob.Status.QUEUED,
                    attempt_n=1,
                )
                segment.current_asr_job = job
                segment.save(update_fields=["current_asr_job", "updated_at"])
        except IntegrityError as exc:
            active = ProcessingJob.objects.filter(
                segment_id=segment.id,
                expected_revision=segment.definition_revision,
                job_type=_ASR_TYPE,
                status__in=list(_ACTIVE),
            ).first()
            raise ActiveJobExistsError(
                "Active ASR job already exists for this segment revision",
                details={"job_id": str(active.id) if active else None},
            ) from exc
        return job, True

    def apply(
        self,
        asr_run_id: uuid.UUID,
        *,
        expected_definition_revision: int,
        actor_user_id: uuid.UUID,
    ) -> AudioSegment:
        run = self.get_run(asr_run_id)
        self.memberships.require_owner(run.project_id, actor_user_id)
        self.memberships.require_active_project(run.project_id)

        with transaction.atomic():
            segment = (
                AudioSegment.objects.select_for_update()
                .select_related("source")
                .get(pk=run.segment_id)
            )
            if segment.deleted_at is not None:
                raise SegmentDeletedError(
                    "Segment is soft-deleted",
                    details={"segment_id": str(segment.id)},
                )
            if segment.definition_revision != expected_definition_revision:
                raise SegmentRevisionConflictError(
                    "Segment definition_revision conflict",
                    details={
                        "segment_id": str(segment.id),
                        "current_definition_revision": segment.definition_revision,
                        "expected_definition_revision": expected_definition_revision,
                    },
                )
            if (
                run.is_stale_result
                or run.segment_revision != segment.definition_revision
                or run.artifact_id != segment.current_artifact_id
            ):
                raise AsrRunNotCurrentError(
                    "ASR run is not current for this segment",
                    details={
                        "asr_run_id": str(run.id),
                        "is_stale_result": run.is_stale_result,
                    },
                )
            previous = segment.transcript or ""
            segment.transcript = run.text
            segment.save(update_fields=["transcript", "updated_at"])
            if previous != (segment.transcript or ""):
                from apps.workspace.services.transcript_span import TranscriptSpanService

                TranscriptSpanService().mark_stale(segment.id)
            return segment

    def complete_asr(
        self,
        job_id: uuid.UUID,
        *,
        result: AsrEngineResult | None = None,
    ) -> ProcessingJob:
        with transaction.atomic():
            job = ProcessingJob.objects.select_for_update().get(pk=job_id)
            segment = (
                AudioSegment.objects.select_for_update()
                .select_related("source")
                .get(pk=job.segment_id)
            )
            if job.job_type != _ASR_TYPE:
                raise InvalidStateTransitionError(
                    "Job is not TRANSCRIBE_SEGMENT_AUDIO",
                    details={"job_id": str(job_id), "job_type": job.job_type},
                )
            if job.status in _TERMINAL:
                raise InvalidStateTransitionError(
                    "Job already terminal",
                    details={"job_id": str(job_id), "status": job.status},
                )

            now = datetime.now(timezone.utc)
            snap = job.config_snapshot or {}

            if job.status == ProcessingJob.Status.QUEUED:
                job.status = ProcessingJob.Status.RUNNING
                job.started_at = now
                job.save(update_fields=["status", "started_at"])
                if job.cancel_requested_at is not None:
                    job.status = ProcessingJob.Status.CANCELLED
                    job.finished_at = now
                    job.save(update_fields=["status", "finished_at"])
                    self._clear_asr_job(segment, job)
                    return job

            if segment.deleted_at is not None or segment.definition_revision != job.expected_revision:
                job.status = ProcessingJob.Status.STALE
                job.finished_at = now
                job.save(update_fields=["status", "finished_at"])
                self._clear_asr_job(segment, job)
                return job

            if job.cancel_requested_at is not None:
                job.status = ProcessingJob.Status.CANCELLED
                job.finished_at = now
                job.save(update_fields=["status", "finished_at"])
                self._clear_asr_job(segment, job)
                return job

            artifact_id_raw = snap.get("artifact_id")
            if not artifact_id_raw:
                return self._fail_asr(
                    job, segment, "ARTIFACT_REQUIRED", "ASR config_snapshot missing artifact_id"
                )

            artifact_id = uuid.UUID(str(artifact_id_raw))
            if segment.current_artifact_id != artifact_id:
                job.status = ProcessingJob.Status.STALE
                job.finished_at = now
                job.save(update_fields=["status", "finished_at"])
                self._clear_asr_job(segment, job)
                return job

            try:
                engine_result = result or self._run_engine(job, snap)
            except AsrEngineError as exc:
                return self._fail_asr(job, segment, exc.code, exc.message[:2000])
            except AsrProviderMisconfiguredError as exc:
                code = str((exc.details or {}).get("code") or "ASR_PROVIDER_MISCONFIGURED")
                return self._fail_asr(job, segment, code, exc.message[:2000])
            except Exception as exc:  # noqa: BLE001
                return self._fail_asr(job, segment, "ASR_ENGINE_ERROR", str(exc)[:2000])

            run = self._persist_run(
                job=job,
                segment=segment,
                snap=snap,
                engine_result=engine_result,
                is_stale=False,
                completed_at=now,
            )
            job.status = ProcessingJob.Status.SUCCEEDED
            job.finished_at = now
            job.error_code = None
            job.error_message = None
            job.save()
            segment.current_asr_job = None
            segment.current_asr_run = run
            segment.save(update_fields=["current_asr_job", "current_asr_run", "updated_at"])
            return job

    def simulate_success(
        self, job_id: uuid.UUID, *, text: str = "fake transcript"
    ) -> ProcessingJob:
        return self.complete_asr(
            job_id,
            result=AsrEngineResult(
                text=text,
                language_detected="vi",
                model_version="fake-0",
                model_path_or_id="fake://model",
            ),
        )

    def _fail_asr(
        self, job: ProcessingJob, segment: AudioSegment, code: str, message: str
    ) -> ProcessingJob:
        job.status = ProcessingJob.Status.FAILED
        job.error_code = code
        job.error_message = message
        job.finished_at = datetime.now(timezone.utc)
        job.save()
        self._clear_asr_job(segment, job)
        return job

    def _clear_asr_job(self, segment: AudioSegment, job: ProcessingJob) -> None:
        if segment.current_asr_job_id == job.id:
            segment.current_asr_job = None
            segment.save(update_fields=["current_asr_job", "updated_at"])

    def _run_engine(self, job: ProcessingJob, snap: dict[str, Any]) -> AsrEngineResult:
        artifact_id = uuid.UUID(str(snap["artifact_id"]))
        artifact = ProcessingArtifact.objects.get(pk=artifact_id)
        if not self.storage.exists(artifact.storage_key):
            raise AsrEngineError("ARTIFACT_MISSING", "Artifact bytes missing from storage")
        audio = self.storage.get(artifact.storage_key)
        provider = str(snap.get("provider") or "local")
        api_key = resolve_runtime_api_key(snap) if provider == "openai" else None
        engine = self._engine_override or build_asr_engine(
            engine_name=str(snap.get("engine") or "fake"),
            model_cache_dir=getattr(settings, "ASR_MODEL_CACHE_DIR", "./storage/whisper-models"),
            download=getattr(settings, "ASR_DOWNLOAD_MODELS", True),
            provider=provider,
            openai_api_key=api_key,
            openai_base_url=snap.get("openai_base_url"),
            openai_timeout_seconds=int(getattr(settings, "ASR_TIMEOUT_SECONDS", 600)),
        )
        config = AsrEngineConfig(
            model_name=str(snap.get("model_name") or "fake"),
            model_size=str(snap.get("model") or snap.get("model_size") or "base"),
            language_requested=str(snap.get("language_requested") or "vi"),
            task=str(snap.get("task") or "transcribe"),
            device=str(snap.get("device") or "cpu"),
            compute_type=str(snap.get("compute_type") or "int8"),
            decode_params=dict(snap.get("decode_params") or {}),
            provider=provider,
            openai_api_key=api_key,
            openai_base_url=snap.get("openai_base_url"),
        )
        return engine.transcribe(audio, config)

    def _persist_run(
        self,
        *,
        job: ProcessingJob,
        segment: AudioSegment,
        snap: dict[str, Any],
        engine_result: AsrEngineResult,
        is_stale: bool,
        completed_at: datetime,
    ) -> AsrRun:
        artifact_id = uuid.UUID(str(snap["artifact_id"]))
        model = str(snap.get("model") or snap.get("model_size") or "base")
        return AsrRun.objects.create(
            segment=segment,
            project_id=job.project_id,
            source_id=job.source_id,
            processing_job=job,
            artifact_id=artifact_id,
            segment_revision=job.expected_revision,
            artifact_checksum=snap.get("artifact_checksum"),
            provider=str(snap.get("provider") or "local"),
            engine=str(snap.get("engine") or "fake"),
            model=model,
            model_name=str(snap.get("model_name") or "fake"),
            model_size=str(snap.get("model_size") or model),
            model_version=engine_result.model_version,
            model_path_or_id=engine_result.model_path_or_id,
            language_requested=str(snap.get("language_requested") or "vi"),
            language_detected=engine_result.language_detected,
            task=str(snap.get("task") or "transcribe"),
            device=snap.get("device"),
            compute_type=snap.get("compute_type"),
            decode_params=dict(snap.get("decode_params") or {}),
            text=engine_result.text or "",
            segments_json=engine_result.segments_json,
            words_json=engine_result.words_json,
            confidence_summary=engine_result.confidence_summary,
            is_stale_result=is_stale,
            completed_at=completed_at,
        )

    def _find_equivalent_succeeded(
        self,
        *,
        segment_id: uuid.UUID,
        segment_revision: int,
        artifact: ProcessingArtifact,
        language_requested: str,
        model: str,
        engine: str,
        provider: str = "local",
    ) -> ProcessingJob | None:
        qs = AsrRun.objects.filter(
            segment_id=segment_id,
            segment_revision=segment_revision,
            artifact_id=artifact.id,
            is_stale_result=False,
            provider=provider,
            engine=engine,
            model=model,
            language_requested=language_requested,
            task="transcribe",
        ).order_by("-created_at")
        for run in qs:
            if artifact.checksum and run.artifact_checksum != artifact.checksum:
                continue
            try:
                job = ProcessingJob.objects.get(pk=run.processing_job_id)
            except ProcessingJob.DoesNotExist:
                continue
            if job.status == ProcessingJob.Status.SUCCEEDED:
                return job
        return None

    def _load_asr_context(
        self, segment_id: uuid.UUID
    ) -> tuple[AudioSegment, VideoSource, Project, ProcessingArtifact]:
        try:
            segment = AudioSegment.objects.select_related("source").get(pk=segment_id)
        except AudioSegment.DoesNotExist as exc:
            raise NotFoundError(
                "Segment not found", details={"segment_id": str(segment_id)}
            ) from exc
        source = segment.source
        project = ProjectService().get(source.project_id)
        if segment.current_artifact_id is None:
            raise ArtifactRequiredError(
                "Segment has no current verified audio artifact",
                details={"segment_id": str(segment_id)},
            )
        try:
            artifact = ProcessingArtifact.objects.get(pk=segment.current_artifact_id)
        except ProcessingArtifact.DoesNotExist as exc:
            raise ArtifactRequiredError(
                "Segment has no current verified audio artifact",
                details={"segment_id": str(segment_id)},
            ) from exc
        if not artifact.verified:
            raise ArtifactNotVerifiedError(
                "Current artifact is not verified",
                details={"artifact_id": str(artifact.id)},
            )
        if not self.storage.exists(artifact.storage_key):
            raise ArtifactRequiredError(
                "Artifact bytes missing from storage",
                details={"artifact_id": str(artifact.id)},
            )
        return segment, source, project, artifact
