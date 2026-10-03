"""ProcessingJob, artifacts, source cache, and HTTP idempotency records."""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q


class ProcessingJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        STALE = "STALE", "Stale"
        CANCELLED = "CANCELLED", "Cancelled"

    class JobType(models.TextChoices):
        EXTRACT_SEGMENT_AUDIO = "EXTRACT_SEGMENT_AUDIO", "Extract segment audio"
        TRANSCRIBE_SEGMENT_AUDIO = "TRANSCRIBE_SEGMENT_AUDIO", "Transcribe segment audio"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    segment = models.ForeignKey(
        "workspace.AudioSegment",
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    source = models.ForeignKey(
        "workspace.VideoSource",
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    project = models.ForeignKey(
        "workspace.Project",
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    expected_revision = models.IntegerField()
    job_type = models.CharField(
        max_length=64,
        choices=JobType.choices,
        default=JobType.EXTRACT_SEGMENT_AUDIO,
    )
    start_seconds = models.FloatField()
    end_seconds = models.FloatField()
    config_snapshot = models.JSONField()
    idempotency_key = models.CharField(max_length=128, null=True, blank=True, unique=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.QUEUED)
    attempt_n = models.IntegerField(default=1)
    retry_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="retries",
    )
    error_code = models.CharField(max_length=64, null=True, blank=True)
    error_message = models.CharField(max_length=2000, null=True, blank=True)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "processing_jobs"
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "QUEUED",
                        "RUNNING",
                        "SUCCEEDED",
                        "FAILED",
                        "STALE",
                        "CANCELLED",
                    ]
                ),
                name="ck_processing_jobs_status",
            ),
            models.CheckConstraint(
                condition=Q(
                    job_type__in=[
                        "EXTRACT_SEGMENT_AUDIO",
                        "TRANSCRIBE_SEGMENT_AUDIO",
                    ]
                ),
                name="ck_processing_jobs_job_type",
            ),
            models.UniqueConstraint(
                fields=["segment", "expected_revision", "job_type"],
                condition=Q(status__in=["QUEUED", "RUNNING"]),
                name="uq_pj_active",
            ),
        ]
        indexes = [
            models.Index(fields=["segment"], name="ix_pj_segment_id"),
            models.Index(fields=["project"], name="ix_pj_project_id"),
            models.Index(fields=["status"], name="ix_pj_status"),
        ]


class ProcessingArtifact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        ProcessingJob,
        on_delete=models.CASCADE,
        related_name="artifact",
    )
    storage_key = models.CharField(max_length=512)
    format = models.CharField(max_length=16)
    sample_rate_hz = models.IntegerField()
    channels = models.IntegerField()
    file_size_bytes = models.IntegerField()
    checksum = models.CharField(max_length=128, null=True, blank=True)
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "processing_artifacts"


class AsrRun(models.Model):
    """Immutable ASR machine candidate (Gate W2/W3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    segment = models.ForeignKey(
        "workspace.AudioSegment",
        on_delete=models.CASCADE,
        related_name="asr_runs",
    )
    project = models.ForeignKey(
        "workspace.Project",
        on_delete=models.CASCADE,
        related_name="asr_runs",
    )
    source = models.ForeignKey(
        "workspace.VideoSource",
        on_delete=models.CASCADE,
        related_name="asr_runs",
    )
    processing_job = models.OneToOneField(
        ProcessingJob,
        on_delete=models.RESTRICT,
        related_name="asr_run",
    )
    artifact = models.ForeignKey(
        ProcessingArtifact,
        on_delete=models.RESTRICT,
        related_name="asr_runs",
    )
    segment_revision = models.IntegerField()
    artifact_checksum = models.CharField(max_length=128, null=True, blank=True)
    provider = models.CharField(max_length=32, default="local")
    engine = models.CharField(max_length=64, default="fake")
    model = models.CharField(max_length=128, default="base")
    model_name = models.CharField(max_length=64)
    model_size = models.CharField(max_length=128)
    model_version = models.CharField(max_length=64, null=True, blank=True)
    model_path_or_id = models.CharField(max_length=512, null=True, blank=True)
    language_requested = models.CharField(max_length=16)
    language_detected = models.CharField(max_length=16, null=True, blank=True)
    task = models.CharField(max_length=32, default="transcribe")
    device = models.CharField(max_length=16, null=True, blank=True)
    compute_type = models.CharField(max_length=32, null=True, blank=True)
    decode_params = models.JSONField(default=dict)
    text = models.TextField()
    segments_json = models.JSONField(null=True, blank=True)
    words_json = models.JSONField(null=True, blank=True)
    confidence_summary = models.JSONField(null=True, blank=True)
    is_stale_result = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField()

    class Meta:
        db_table = "asr_runs"
        indexes = [
            models.Index(fields=["segment", "created_at"], name="ix_asr_runs_seg_created"),
            models.Index(fields=["project", "created_at"], name="ix_asr_runs_proj_created"),
            models.Index(fields=["artifact"], name="ix_asr_runs_artifact_id"),
        ]


class UserAsrPreferences(models.Model):
    user = models.OneToOneField(
        "workspace.AppUser",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="asr_preferences",
    )
    use_system_defaults = models.BooleanField(default=True)
    provider = models.CharField(max_length=32, null=True, blank=True)
    local_model = models.CharField(max_length=128, null=True, blank=True)
    local_device = models.CharField(max_length=16, null=True, blank=True)
    local_compute_type = models.CharField(max_length=32, null=True, blank=True)
    openai_model = models.CharField(max_length=128, null=True, blank=True)
    openai_api_key_encrypted = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_asr_preferences"


class SystemAsrSettings(models.Model):
    id = models.IntegerField(primary_key=True, default=1)
    provider = models.CharField(max_length=32, null=True, blank=True)
    local_model = models.CharField(max_length=128, null=True, blank=True)
    local_device = models.CharField(max_length=16, null=True, blank=True)
    local_compute_type = models.CharField(max_length=32, null=True, blank=True)
    openai_enabled = models.BooleanField(null=True, blank=True)
    openai_default_model = models.CharField(max_length=128, null=True, blank=True)
    openai_base_url = models.CharField(max_length=512, null=True, blank=True)
    openai_api_key_encrypted = models.TextField(null=True, blank=True)
    updated_by_user = models.ForeignKey(
        "workspace.AppUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_asr_settings"
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="ck_system_asr_settings_singleton"),
        ]


class UserAiPreferences(models.Model):
    """Per-user AI Provider preferences (Gate W8.1). Not ASR."""

    user = models.OneToOneField(
        "workspace.AppUser",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="ai_preferences",
    )
    use_system_defaults = models.BooleanField(default=True)
    provider = models.CharField(max_length=32, null=True, blank=True)
    ollama_base_url = models.CharField(max_length=512, null=True, blank=True)
    ollama_model = models.CharField(max_length=128, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_ai_preferences"


class SystemAiSettings(models.Model):
    """Singleton system AI Provider defaults (Gate W8.1). Not ASR."""

    id = models.IntegerField(primary_key=True, default=1)
    enabled = models.BooleanField(null=True, blank=True)
    provider = models.CharField(max_length=32, null=True, blank=True)
    ollama_base_url = models.CharField(max_length=512, null=True, blank=True)
    ollama_default_model = models.CharField(max_length=128, null=True, blank=True)
    updated_by_user = models.ForeignKey(
        "workspace.AppUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_ai_settings"
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="ck_system_ai_settings_singleton"),
        ]


class AiAssistRun(models.Model):
    """Immutable AI assist candidate run (Gate W8.2/W8.3). Not ASR."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    segment = models.ForeignKey(
        "workspace.AudioSegment",
        on_delete=models.CASCADE,
        related_name="ai_assist_runs",
    )
    project = models.ForeignKey(
        "workspace.Project",
        on_delete=models.CASCADE,
        related_name="ai_assist_runs",
    )
    source = models.ForeignKey(
        "workspace.VideoSource",
        on_delete=models.CASCADE,
        related_name="ai_assist_runs",
    )
    created_by_user = models.ForeignKey(
        "workspace.AppUser",
        on_delete=models.RESTRICT,
        related_name="ai_assist_runs",
    )
    kind = models.CharField(max_length=64)
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=128)
    segment_revision = models.IntegerField()
    input_text = models.TextField()
    output_text = models.TextField()
    prompt_version = models.CharField(max_length=32, default="v1")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField()
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ai_assist_runs"
        indexes = [
            models.Index(fields=["segment", "created_at"], name="ix_ai_assist_runs_seg_created"),
        ]


class SourceMediaCache(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.OneToOneField(
        "workspace.VideoSource",
        on_delete=models.CASCADE,
        related_name="media_cache",
    )
    storage_key = models.CharField(max_length=512)
    file_size_bytes = models.IntegerField(null=True, blank=True)
    checksum = models.CharField(max_length=128, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "source_media_cache"


class IdempotencyRecord(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_user = models.ForeignKey(
        "workspace.AppUser",
        on_delete=models.CASCADE,
        related_name="idempotency_records",
    )
    method = models.CharField(max_length=16)
    route = models.CharField(max_length=512)
    key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.IN_PROGRESS)
    response_status = models.IntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "idempotency_records"
        constraints = [
            models.UniqueConstraint(
                fields=["actor_user", "method", "route", "key"],
                name="uq_idem_scope",
            ),
        ]
        indexes = [
            models.Index(fields=["created_at"], name="ix_idem_created_at"),
        ]
