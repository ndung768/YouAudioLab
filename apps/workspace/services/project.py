"""Project and settings domain service."""

from __future__ import annotations

import uuid

from apps.core.errors import NotFoundError, ProjectArchivedError, ValidationError
from apps.workspace.models import Project, ProjectMembership, ProjectSettings
from apps.workspace.services.membership import MembershipService


class ProjectService:
    def __init__(self) -> None:
        self.memberships = MembershipService()

    def create(
        self,
        *,
        name: str,
        owner_user_id: uuid.UUID,
        description: str | None = None,
        language: str = "vi",
    ) -> Project:
        name = (name or "").strip()
        if not name:
            raise ValidationError(
                "Project name is required",
                details={"fields": [{"field": "name", "code": "REQUIRED"}]},
            )
        language = (language or "vi").strip() or "vi"

        project = Project.objects.create(
            name=name,
            description=description,
            language=language,
            status=Project.Status.ACTIVE,
        )
        ProjectSettings.objects.create(
            project=project,
            output_format="WAV",
            encoding="PCM",
            sample_rate_hz=16000,
            channels=1,
            loudness_normalization=False,
            naming_convention=None,
        )
        ProjectMembership.objects.create(
            project=project,
            user_id=owner_user_id,
            role=ProjectMembership.Role.OWNER,
        )
        return project

    def get(self, project_id: uuid.UUID) -> Project:
        try:
            return Project.objects.select_related("settings").get(pk=project_id)
        except Project.DoesNotExist as exc:
            raise NotFoundError(
                "Project not found",
                details={"project_id": str(project_id)},
            ) from exc

    def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[Project]:
        qs = Project.objects.filter(
            memberships__user_id=user_id,
            memberships__revoked_at__isnull=True,
        ).distinct().order_by("-created_at")
        if status is not None:
            qs = qs.filter(status=status)
        return list(qs)

    def list_owned_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[Project]:
        """Projects where the user has an active OWNER membership."""
        from django.db.models import Count

        qs = (
            Project.objects.filter(
                memberships__user_id=user_id,
                memberships__role=ProjectMembership.Role.OWNER,
                memberships__revoked_at__isnull=True,
            )
            .annotate(
                source_count=Count("sources", distinct=True),
                segment_count=Count("sources__segments", distinct=True),
            )
            .distinct()
            .order_by("-created_at")
        )
        if status is not None:
            qs = qs.filter(status=status)
        return list(qs)

    def list_participated_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[Project]:
        """Projects where the user is an active non-owner member (e.g. ANNOTATOR)."""
        from django.db.models import Count

        owned_ids = ProjectMembership.objects.filter(
            user_id=user_id,
            role=ProjectMembership.Role.OWNER,
            revoked_at__isnull=True,
        ).values_list("project_id", flat=True)

        qs = (
            Project.objects.filter(
                memberships__user_id=user_id,
                memberships__revoked_at__isnull=True,
            )
            .exclude(id__in=owned_ids)
            .annotate(
                source_count=Count("sources", distinct=True),
                segment_count=Count("sources__segments", distinct=True),
            )
            .distinct()
            .order_by("-created_at")
        )
        if status is not None:
            qs = qs.filter(status=status)
        return list(qs)

    def update(
        self,
        project_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        name: str | None = None,
        description: str | None | object = ...,
        language: str | None = None,
        license: str | None | object = ...,
        consent_notes: str | None | object = ...,
    ) -> Project:
        self.memberships.require_owner(project_id, actor_user_id)
        project = self.memberships.require_active_project(project_id)

        if name is not None:
            name = name.strip()
            if not name:
                raise ValidationError(
                    "Project name cannot be empty",
                    details={"fields": [{"field": "name", "code": "REQUIRED"}]},
                )
            project.name = name
        if description is not ...:
            project.description = description  # type: ignore[assignment]
        if language is not None:
            project.language = language.strip() or project.language
        if license is not ...:
            value = (license or "").strip() or None  # type: ignore[operator]
            project.license = value
        if consent_notes is not ...:
            value = (consent_notes or "").strip() or None  # type: ignore[operator]
            project.consent_notes = value
        project.save()
        return project

    def archive(
        self,
        project_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> Project:
        self.memberships.require_owner(project_id, actor_user_id)
        project = self.get(project_id)
        if project.status != Project.Status.ARCHIVED:
            project.status = Project.Status.ARCHIVED
            project.save(update_fields=["status", "updated_at"])
        return project

    def get_settings(self, project_id: uuid.UUID) -> ProjectSettings:
        project = self.get(project_id)
        try:
            return project.settings
        except ProjectSettings.DoesNotExist as exc:
            raise NotFoundError(
                "Project settings not found",
                details={"project_id": str(project_id)},
            ) from exc

    def update_settings(
        self,
        project_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        output_format: str,
        encoding: str,
        sample_rate_hz: int,
        channels: int,
        loudness_normalization: bool,
        naming_convention: str | None = None,
        require_audio_review: bool | None = None,
        require_transcript: bool | None = None,
        require_annotation: bool | None = None,
        blind_annotators: bool | None = None,
        asr_provider: str | None = None,
        asr_model: str | None = None,
        ai_enabled: bool | None = None,
        ai_provider: str | None = None,
        ai_ollama_base_url: str | None = None,
        ai_ollama_model: str | None = None,
        apply_asr_protocol: bool = False,
        apply_ai_protocol: bool = False,
    ) -> ProjectSettings:
        self.memberships.require_owner(project_id, actor_user_id)
        self.memberships.require_active_project(project_id)
        settings = self.get_settings(project_id)

        if sample_rate_hz <= 0:
            raise ValidationError(
                "sample_rate_hz must be positive",
                details={"fields": [{"field": "sample_rate_hz", "code": "INVALID"}]},
            )
        if channels not in (1, 2):
            raise ValidationError(
                "channels must be 1 or 2",
                details={"fields": [{"field": "channels", "code": "INVALID"}]},
            )

        settings.output_format = output_format
        settings.encoding = encoding
        settings.sample_rate_hz = sample_rate_hz
        settings.channels = channels
        settings.loudness_normalization = loudness_normalization
        settings.naming_convention = naming_convention
        if require_audio_review is not None:
            settings.require_audio_review = require_audio_review
        if require_transcript is not None:
            settings.require_transcript = require_transcript
        if require_annotation is not None:
            settings.require_annotation = require_annotation
        if blind_annotators is not None:
            settings.blind_annotators = blind_annotators

        if apply_asr_protocol:
            cleaned = (asr_provider or "").strip().lower() or None
            if cleaned and cleaned not in {"local", "openai"}:
                raise ValidationError(
                    "Unsupported project ASR provider",
                    details={
                        "fields": [
                            {
                                "field": "asr_provider",
                                "code": "INVALID",
                                "allowed": ["local", "openai"],
                            }
                        ]
                    },
                )
            settings.asr_provider = cleaned
            settings.asr_model = (asr_model or "").strip() or None

        if apply_ai_protocol:
            settings.ai_enabled = ai_enabled
            settings.ai_provider = (ai_provider or "").strip().lower() or None
            settings.ai_ollama_base_url = (
                (ai_ollama_base_url or "").strip().rstrip("/") or None
            )
            settings.ai_ollama_model = (ai_ollama_model or "").strip() or None

        settings.save()
        return settings

    def assert_writable(self, project_id: uuid.UUID) -> Project:
        project = self.get(project_id)
        if project.status == Project.Status.ARCHIVED:
            raise ProjectArchivedError(
                "Project is archived",
                details={"project_id": str(project_id)},
            )
        return project
