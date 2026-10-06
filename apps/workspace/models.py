"""Workspace domain models — users, projects, sources, segments, labels, annotations."""

from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AppUserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(
        self,
        login_identifier: str,
        display_name: str,
        password: str | None,
        **extra_fields,
    ):
        login = (login_identifier or "").strip().lower()
        name = (display_name or "").strip()
        if not login:
            raise ValueError("login_identifier is required")
        if not name:
            raise ValueError("display_name is required")
        status = extra_fields.pop("status", AppUser.Status.ACTIVE)
        extra_fields.setdefault("is_active", status == AppUser.Status.ACTIVE)
        user = self.model(
            login_identifier=login,
            display_name=name,
            status=status,
            **extra_fields,
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(
        self,
        login_identifier: str,
        display_name: str,
        password: str | None = None,
        **extra_fields,
    ):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(login_identifier, display_name, password, **extra_fields)

    def create_superuser(
        self,
        login_identifier: str,
        display_name: str,
        password: str | None = None,
        **extra_fields,
    ):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("status", AppUser.Status.ACTIVE)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(login_identifier, display_name, password, **extra_fields)


class AppUser(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """AUTH_USER_MODEL — Gate A1 password + JWT; HTML uses Django session auth."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=255)
    login_identifier = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    # Django 6 AbstractBaseUser only sets is_active as a class attribute; store it.
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this user should be treated as active.",
    )
    is_staff = models.BooleanField(default=False)

    objects = AppUserManager()

    USERNAME_FIELD = "login_identifier"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        db_table = "users"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["ACTIVE", "INACTIVE"]),
                name="ck_users_status",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name

    def save(self, *args, **kwargs):
        if self.status == self.Status.ACTIVE:
            self.is_active = True
        elif self.status == self.Status.INACTIVE:
            self.is_active = False
        super().save(*args, **kwargs)


class Project(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ARCHIVED = "ARCHIVED", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=2000, null=True, blank=True)
    language = models.CharField(max_length=16, default="vi")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    license = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text="Corpus license, e.g. CC-BY-4.0 or research-only.",
    )
    consent_notes = models.TextField(
        null=True,
        blank=True,
        help_text="Human-subjects / speaker-consent notes for this corpus.",
    )

    class Meta:
        db_table = "projects"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["ACTIVE", "ARCHIVED"]),
                name="ck_projects_status",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ProjectSettings(models.Model):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="settings",
    )
    output_format = models.CharField(max_length=16, default="WAV")
    encoding = models.CharField(max_length=16, default="PCM")
    sample_rate_hz = models.IntegerField(default=16000)
    channels = models.IntegerField(default=1)
    loudness_normalization = models.BooleanField(default=False)
    naming_convention = models.CharField(max_length=255, null=True, blank=True)
    require_audio_review = models.BooleanField(
        default=True,
        help_text="Export readiness requires OWNER Audio OK review.",
    )
    require_transcript = models.BooleanField(
        default=True,
        help_text="Export readiness requires a non-empty canonical transcript.",
    )
    require_annotation = models.BooleanField(
        default=True,
        help_text="Export readiness requires at least one active annotation.",
    )
    blind_annotators = models.BooleanField(
        default=True,
        help_text="When True, ANNOTATOR members cannot see peer labels.",
    )
    # Research protocol: ASR / AI defaults for this project (null = inherit account/system).
    asr_provider = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        help_text="local | openai; null inherits account/system ASR defaults.",
    )
    asr_model = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Whisper size or OpenAI model id; null inherits.",
    )
    ai_enabled = models.BooleanField(
        null=True,
        blank=True,
        help_text="null inherits system AI enabled flag.",
    )
    ai_provider = models.CharField(max_length=32, null=True, blank=True)
    ai_ollama_base_url = models.CharField(max_length=512, null=True, blank=True)
    ai_ollama_model = models.CharField(max_length=128, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "project_settings"


class ProjectMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        ANNOTATOR = "ANNOTATOR", "Annotator"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=32, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "project_memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "user"],
                name="uq_pm_project_user",
            ),
            models.CheckConstraint(
                condition=Q(role__in=["OWNER", "ANNOTATOR"]),
                name="ck_pm_role",
            ),
        ]
        indexes = [
            models.Index(fields=["user"], name="ix_pm_user_id"),
            models.Index(fields=["project"], name="ix_pm_project_id"),
            models.Index(
                fields=["project", "user"],
                name="ix_pm_active",
                condition=Q(revoked_at__isnull=True),
            ),
        ]


class VideoSource(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING_METADATA = "PENDING_METADATA", "Pending metadata"
        READY = "READY", "Ready"
        METADATA_FAILED = "METADATA_FAILED", "Metadata failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sources")
    youtube_video_id = models.CharField(max_length=32)
    youtube_url = models.CharField(max_length=512)
    title = models.CharField(max_length=512, null=True, blank=True)
    channel_name = models.CharField(max_length=255, null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    source_status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_METADATA,
    )
    metadata_json = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "video_sources"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "youtube_video_id"],
                name="uq_vs_project_video",
            ),
            models.CheckConstraint(
                condition=Q(
                    source_status__in=[
                        "PENDING_METADATA",
                        "READY",
                        "METADATA_FAILED",
                    ]
                ),
                name="ck_vs_source_status",
            ),
        ]


class AudioSegment(TimeStampedModel):
    class ProcessingStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(VideoSource, on_delete=models.CASCADE, related_name="segments")
    segment_index = models.IntegerField()
    start_seconds = models.FloatField()
    end_seconds = models.FloatField()
    duration_seconds = models.FloatField()
    transcript = models.CharField(max_length=10000, null=True, blank=True)
    definition_revision = models.IntegerField(default=1)
    processing_status = models.CharField(
        max_length=32,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
    )
    current_job = models.ForeignKey(
        "processing.ProcessingJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    current_artifact = models.ForeignKey(
        "processing.ProcessingArtifact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    current_asr_job = models.ForeignKey(
        "processing.ProcessingJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    current_asr_run = models.ForeignKey(
        "processing.AsrRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    audio_reviewed_at = models.DateTimeField(null=True, blank=True)
    audio_reviewed_by = models.ForeignKey(
        AppUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="segments_audio_reviewed",
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "audio_segments"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "segment_index"],
                name="uq_as_source_index",
            ),
            models.CheckConstraint(
                condition=Q(start_seconds__gte=0),
                name="ck_as_start_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(end_seconds__gt=models.F("start_seconds")),
                name="ck_as_end_gt_start",
            ),
            models.CheckConstraint(
                condition=Q(definition_revision__gte=1),
                name="ck_as_revision_min",
            ),
            models.CheckConstraint(
                condition=Q(
                    processing_status__in=["PENDING", "PROCESSING", "COMPLETED", "FAILED"]
                ),
                name="ck_as_proc_status",
            ),
        ]

    @property
    def project_id(self) -> uuid.UUID:
        return self.source.project_id


class LabelScope(models.TextChoices):
    SEGMENT = "SEGMENT", "Whole segment"
    SPAN = "SPAN", "Text in transcript"
    BOTH = "BOTH", "Both"


LABEL_SEGMENT_SCOPES = (LabelScope.SEGMENT, LabelScope.BOTH)
LABEL_SPAN_SCOPES = (LabelScope.SPAN, LabelScope.BOTH)


class Label(TimeStampedModel):
    """User-owned label catalog (AnnotaHub-style). Reusable across projects."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="labels")
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=2000, null=True, blank=True)
    include_guidance = models.TextField(
        null=True,
        blank=True,
        help_text="Operational definition: what to include for this label.",
    )
    exclude_guidance = models.TextField(
        null=True,
        blank=True,
        help_text="Operational definition: what to exclude for this label.",
    )
    color = models.CharField(max_length=32, null=True, blank=True)
    default_scope = models.CharField(
        max_length=16,
        choices=LabelScope.choices,
        default=LabelScope.BOTH,
        help_text="Default use when this catalog label is added to a project.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="When false, label cannot be added to new projects.",
    )

    class Meta:
        db_table = "labels"
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "owner",
                name="uq_label_owner_name_lower",
            ),
            models.CheckConstraint(
                condition=Q(default_scope__in=["SEGMENT", "SPAN", "BOTH"]),
                name="ck_label_default_scope",
            ),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ProjectLabel(models.Model):
    """Assigns a user-owned Label to a project with optional display overrides."""

    Scope = LabelScope
    SEGMENT_SCOPES = LABEL_SEGMENT_SCOPES
    SPAN_SCOPES = LABEL_SPAN_SCOPES

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=16, choices=LabelScope.choices, default=LabelScope.BOTH)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="project_labels")
    label = models.ForeignKey(Label, on_delete=models.CASCADE, related_name="project_labels")
    override_name = models.CharField(max_length=255, null=True, blank=True)
    override_description = models.CharField(max_length=2000, null=True, blank=True)
    override_include_guidance = models.TextField(null=True, blank=True)
    override_exclude_guidance = models.TextField(null=True, blank=True)
    override_color = models.CharField(max_length=32, null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "project_labels"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "label"],
                name="uq_project_label",
            ),
            models.CheckConstraint(
                condition=Q(scope__in=["SEGMENT", "SPAN", "BOTH"]),
                name="ck_pl_scope",
            ),
        ]

    @property
    def for_segment(self) -> bool:
        return self.scope in self.SEGMENT_SCOPES

    @property
    def for_span(self) -> bool:
        return self.scope in self.SPAN_SCOPES

    @property
    def display_name(self) -> str:
        return self.override_name or self.label.name

    @property
    def display_description(self) -> str | None:
        if self.override_description is not None:
            return self.override_description
        return self.label.description

    @property
    def display_include_guidance(self) -> str | None:
        if self.override_include_guidance is not None:
            return self.override_include_guidance
        return self.label.include_guidance

    @property
    def display_exclude_guidance(self) -> str | None:
        if self.override_exclude_guidance is not None:
            return self.override_exclude_guidance
        return self.label.exclude_guidance

    @property
    def display_color(self) -> str | None:
        return self.override_color or self.label.color

    def __str__(self) -> str:
        return f"{self.project_id}: {self.display_name}"


class AssignmentBatch(models.Model):
    """Owner action grouping segment assignments created together."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="assignment_batches")
    created_by = models.ForeignKey(
        AppUser,
        on_delete=models.RESTRICT,
        related_name="assignment_batches_created",
    )
    name = models.CharField(max_length=255, null=True, blank=True)
    source = models.ForeignKey(
        "VideoSource",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignment_batches",
    )
    assignment_group_id = models.UUIDField(default=uuid.uuid4, editable=False)
    notes = models.CharField(max_length=2000, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assignment_batches"
        ordering = ["-created_at"]


class AnnotationAssignment(models.Model):
    """Work queue item: assignee should annotate a segment (distinct from SegmentAnnotation)."""

    class Status(models.TextChoices):
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"
        RELEASED = "RELEASED", "Released"

    ACTIVE_STATUSES = (Status.ASSIGNED, Status.IN_PROGRESS)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="assignments")
    segment = models.ForeignKey(
        AudioSegment,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    assignee = models.ForeignKey(
        AppUser,
        on_delete=models.RESTRICT,
        related_name="annotation_assignments",
    )
    assigned_by = models.ForeignKey(
        AppUser,
        on_delete=models.RESTRICT,
        related_name="assignments_created",
    )
    batch = models.ForeignKey(
        AssignmentBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
    )
    assignment_group_id = models.UUIDField(default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.ASSIGNED,
        db_index=True,
    )
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "annotation_assignments"
        constraints = [
            models.UniqueConstraint(
                fields=["segment", "assignee", "assignment_group_id"],
                condition=Q(status__in=["ASSIGNED", "IN_PROGRESS"]),
                name="uq_aa_active_segment_assignee_group",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=["ASSIGNED", "IN_PROGRESS", "COMPLETED", "RELEASED"],
                ),
                name="ck_aa_status",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "status"], name="ix_aa_project_status"),
            models.Index(fields=["assignee", "status"], name="ix_aa_assignee_status"),
        ]
        ordering = ["-priority", "created_at"]


class SegmentAnnotation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    segment = models.ForeignKey(
        AudioSegment,
        on_delete=models.CASCADE,
        related_name="annotations",
    )
    label = models.ForeignKey(
        ProjectLabel,
        on_delete=models.CASCADE,
        related_name="annotations",
    )
    annotator = models.ForeignKey(
        AppUser,
        on_delete=models.RESTRICT,
        related_name="annotations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        AppUser,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="removed_annotations",
    )

    class Meta:
        db_table = "segment_annotations"
        constraints = [
            models.UniqueConstraint(
                fields=["segment", "label", "annotator"],
                condition=Q(removed_at__isnull=True),
                name="uq_sa_active",
            ),
        ]
        indexes = [
            models.Index(fields=["segment"], name="ix_sa_segment_id"),
            models.Index(fields=["annotator"], name="ix_sa_annotator_id"),
        ]


class SegmentGoldLabel(models.Model):
    """OWNER-adjudicated gold label for a segment (distinct from annotator episodes)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    segment = models.ForeignKey(
        AudioSegment,
        on_delete=models.CASCADE,
        related_name="gold_labels",
    )
    label = models.ForeignKey(
        ProjectLabel,
        on_delete=models.CASCADE,
        related_name="gold_labels",
    )
    adjudicated_by = models.ForeignKey(
        AppUser,
        on_delete=models.RESTRICT,
        related_name="gold_labels_adjudicated",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "segment_gold_labels"
        constraints = [
            models.UniqueConstraint(
                fields=["segment", "label"],
                name="uq_sgl_segment_label",
            ),
        ]
        indexes = [
            models.Index(fields=["segment"], name="ix_sgl_segment_id"),
        ]
        ordering = ["created_at"]


class TranscriptSpan(models.Model):
    """Annotator label on a character span of the accepted transcript.

    Distinct from SegmentAnnotation, which covers the whole segment.
    Offsets are Python indexes into AudioSegment.transcript at assign time.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    segment = models.ForeignKey(
        AudioSegment,
        on_delete=models.CASCADE,
        related_name="transcript_spans",
    )
    label = models.ForeignKey(
        ProjectLabel,
        on_delete=models.CASCADE,
        related_name="transcript_spans",
    )
    annotator = models.ForeignKey(
        AppUser,
        on_delete=models.RESTRICT,
        related_name="transcript_spans",
    )
    start_char = models.PositiveIntegerField()
    end_char = models.PositiveIntegerField()
    quote = models.TextField()
    span_group = models.UUIDField(default=uuid.uuid4, editable=False)
    transcript_sha256 = models.CharField(max_length=64)
    stale = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        AppUser,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="removed_transcript_spans",
    )

    class Meta:
        db_table = "transcript_spans"
        constraints = [
            models.UniqueConstraint(
                fields=["segment", "annotator", "label", "start_char", "end_char"],
                condition=Q(removed_at__isnull=True, stale=False),
                name="uq_ts_active",
            ),
            models.CheckConstraint(
                condition=Q(end_char__gt=models.F("start_char")),
                name="ck_ts_end_gt_start",
            ),
        ]
        indexes = [
            models.Index(fields=["segment"], name="ix_ts_segment_id"),
            models.Index(fields=["annotator"], name="ix_ts_annotator_id"),
        ]
        ordering = ["start_char", "end_char", "created_at"]
