"""DRF serializers matching the FastAPI /api/v1 field names."""

from __future__ import annotations

from rest_framework import serializers


class UserCreateSerializer(serializers.Serializer):
    display_name = serializers.CharField()
    login_identifier = serializers.CharField()


class AuthRegisterSerializer(serializers.Serializer):
    display_name = serializers.CharField()
    login_identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)


class AuthLoginSerializer(serializers.Serializer):
    login_identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)


class UserOutSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()
    login_identifier = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()


class MeOutSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    login_identifier = serializers.CharField()


class ProjectCreateSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True, required=False)
    language = serializers.CharField(required=False, default="vi")


class ProjectUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    description = serializers.CharField(allow_null=True, required=False)
    language = serializers.CharField(required=False)
    license = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    consent_notes = serializers.CharField(allow_null=True, required=False, allow_blank=True)


class ProjectSettingsUpdateSerializer(serializers.Serializer):
    output_format = serializers.CharField()
    encoding = serializers.CharField()
    sample_rate_hz = serializers.IntegerField()
    channels = serializers.IntegerField()
    loudness_normalization = serializers.BooleanField()
    naming_convention = serializers.CharField(allow_null=True, required=False)
    blind_annotators = serializers.BooleanField(required=False)
    asr_provider = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    asr_model = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    ai_enabled = serializers.BooleanField(allow_null=True, required=False)
    ai_provider = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    ai_ollama_base_url = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    ai_ollama_model = serializers.CharField(allow_null=True, required=False, allow_blank=True)


class MemberCreateSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    role = serializers.CharField(required=False, default="ANNOTATOR")


class SourceCreateSerializer(serializers.Serializer):
    youtube_url = serializers.CharField()


class SourceUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(allow_null=True, required=False)
    channel_name = serializers.CharField(allow_null=True, required=False)


class SegmentCreateSerializer(serializers.Serializer):
    start_seconds = serializers.FloatField()
    end_seconds = serializers.FloatField()
    transcript = serializers.CharField(allow_null=True, required=False)


class SegmentUpdateSerializer(serializers.Serializer):
    expected_definition_revision = serializers.IntegerField()
    start_seconds = serializers.FloatField(required=False)
    end_seconds = serializers.FloatField(required=False)
    transcript = serializers.CharField(allow_null=True, required=False)


class LabelCreateSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True, required=False)
    color = serializers.CharField(allow_null=True, required=False)
    sort_order = serializers.IntegerField(required=False, default=0)


class LabelUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    description = serializers.CharField(allow_null=True, required=False)
    color = serializers.CharField(allow_null=True, required=False)
    sort_order = serializers.IntegerField(required=False)


class AnnotationCreateSerializer(serializers.Serializer):
    label_id = serializers.UUIDField()


class AssignmentBatchCreateSerializer(serializers.Serializer):
    assignee_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    source_id = serializers.UUIDField(required=False, allow_null=True)
    segment_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_null=True,
    )
    limit = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    distribute = serializers.ChoiceField(
        choices=["split", "all"],
        required=False,
        default="split",
    )
    priority = serializers.IntegerField(required=False, default=0)
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    assignment_group_id = serializers.UUIDField(required=False, allow_null=True)


class AssignmentReassignSerializer(serializers.Serializer):
    new_assignee_id = serializers.UUIDField()


class JobSubmitSerializer(serializers.Serializer):
    expected_definition_revision = serializers.IntegerField()


class AsrJobSubmitSerializer(serializers.Serializer):
    expected_definition_revision = serializers.IntegerField()
    language = serializers.CharField(required=False, allow_null=True)
    model_size = serializers.CharField(required=False, allow_null=True)
    provider = serializers.CharField(required=False, allow_null=True)
    model = serializers.CharField(required=False, allow_null=True)
    force = serializers.BooleanField(required=False, default=False)


class AsrRunApplySerializer(serializers.Serializer):
    expected_definition_revision = serializers.IntegerField()


class AiAssistCreateSerializer(serializers.Serializer):
    expected_definition_revision = serializers.IntegerField()
    kind = serializers.CharField(required=False, default="transcript_cleanup")


class AiAssistApplySerializer(serializers.Serializer):
    expected_definition_revision = serializers.IntegerField()


def user_out(user) -> dict:
    return {
        "id": str(user.id),
        "display_name": user.display_name,
        "login_identifier": user.login_identifier,
        "status": user.status,
        "created_at": user.created_at.isoformat(),
    }


def project_out(project) -> dict:
    return {
        "project_id": str(project.id),
        "name": project.name,
        "description": project.description,
        "language": project.language,
        "status": project.status,
        "license": project.license,
        "consent_notes": project.consent_notes,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def settings_out(settings) -> dict:
    return {
        "project_id": str(settings.project_id),
        "output_format": settings.output_format,
        "encoding": settings.encoding,
        "sample_rate_hz": settings.sample_rate_hz,
        "channels": settings.channels,
        "loudness_normalization": settings.loudness_normalization,
        "naming_convention": settings.naming_convention,
        "require_audio_review": settings.require_audio_review,
        "require_transcript": settings.require_transcript,
        "require_annotation": settings.require_annotation,
        "blind_annotators": settings.blind_annotators,
        "asr_provider": settings.asr_provider,
        "asr_model": settings.asr_model,
        "ai_enabled": settings.ai_enabled,
        "ai_provider": settings.ai_provider,
        "ai_ollama_base_url": settings.ai_ollama_base_url,
        "ai_ollama_model": settings.ai_ollama_model,
        "updated_at": settings.updated_at.isoformat(),
    }


def member_out(membership) -> dict:
    return {
        "membership_id": str(membership.id),
        "project_id": str(membership.project_id),
        "user_id": str(membership.user_id),
        "role": membership.role,
        "created_at": membership.created_at.isoformat(),
        "revoked_at": membership.revoked_at.isoformat() if membership.revoked_at else None,
    }


def source_out(source) -> dict:
    return {
        "source_id": str(source.id),
        "project_id": str(source.project_id),
        "youtube_url": source.youtube_url,
        "youtube_video_id": source.youtube_video_id,
        "title": source.title,
        "channel_name": source.channel_name,
        "duration_seconds": source.duration_seconds,
        "source_status": source.source_status,
        "created_at": source.created_at.isoformat(),
        "updated_at": source.updated_at.isoformat(),
    }


def segment_out(segment, project_id) -> dict:
    return {
        "segment_id": str(segment.id),
        "source_id": str(segment.source_id),
        "project_id": str(project_id),
        "segment_index": segment.segment_index,
        "start_seconds": segment.start_seconds,
        "end_seconds": segment.end_seconds,
        "duration_seconds": segment.duration_seconds,
        "transcript": segment.transcript,
        "definition_revision": segment.definition_revision,
        "processing_status": segment.processing_status,
        "current_job_id": str(segment.current_job_id) if segment.current_job_id else None,
        "current_artifact_id": (
            str(segment.current_artifact_id) if segment.current_artifact_id else None
        ),
        "current_asr_job_id": (
            str(segment.current_asr_job_id) if segment.current_asr_job_id else None
        ),
        "current_asr_run_id": (
            str(segment.current_asr_run_id) if segment.current_asr_run_id else None
        ),
        "audio_reviewed_at": (
            segment.audio_reviewed_at.isoformat() if segment.audio_reviewed_at else None
        ),
        "audio_reviewed_by": (
            str(segment.audio_reviewed_by_id) if segment.audio_reviewed_by_id else None
        ),
        "deleted_at": segment.deleted_at.isoformat() if segment.deleted_at else None,
        "created_at": segment.created_at.isoformat(),
        "updated_at": segment.updated_at.isoformat(),
    }


def label_out(project_label) -> dict:
    canonical = project_label.label
    return {
        "label_id": str(project_label.id),
        "canonical_label_id": str(canonical.id),
        "project_id": str(project_label.project_id),
        "name": project_label.display_name,
        "description": project_label.display_description,
        "include_guidance": project_label.display_include_guidance,
        "exclude_guidance": project_label.display_exclude_guidance,
        "color": project_label.display_color,
        "scope": project_label.scope,
        "is_active": canonical.is_active,
        "sort_order": project_label.sort_order,
        "created_at": canonical.created_at.isoformat(),
        "updated_at": canonical.updated_at.isoformat(),
    }


def canonical_label_out(label) -> dict:
    return {
        "label_id": str(label.id),
        "name": label.name,
        "description": label.description,
        "include_guidance": label.include_guidance,
        "exclude_guidance": label.exclude_guidance,
        "color": label.color,
        "default_scope": label.default_scope,
        "is_active": label.is_active,
        "project_count": getattr(label, "project_count", None),
        "usage_count": getattr(label, "usage_count", None),
        "created_at": label.created_at.isoformat(),
        "updated_at": label.updated_at.isoformat(),
    }


def annotation_out(ann) -> dict:
    return {
        "annotation_id": str(ann.id),
        "segment_id": str(ann.segment_id),
        "label_id": str(ann.label_id),
        "annotator_id": str(ann.annotator_id),
        "created_at": ann.created_at.isoformat(),
        "removed_at": ann.removed_at.isoformat() if ann.removed_at else None,
        "removed_by": str(ann.removed_by_id) if ann.removed_by_id else None,
    }


def assignment_out(assignment) -> dict:
    segment = assignment.segment
    return {
        "assignment_id": str(assignment.id),
        "project_id": str(assignment.project_id),
        "segment_id": str(assignment.segment_id),
        "source_id": str(segment.source_id) if segment.source_id else None,
        "assignee_id": str(assignment.assignee_id),
        "assignee_name": assignment.assignee.display_name,
        "assigned_by_id": str(assignment.assigned_by_id),
        "batch_id": str(assignment.batch_id) if assignment.batch_id else None,
        "assignment_group_id": str(assignment.assignment_group_id),
        "status": assignment.status,
        "priority": assignment.priority,
        "created_at": assignment.created_at.isoformat(),
        "started_at": assignment.started_at.isoformat() if assignment.started_at else None,
        "completed_at": assignment.completed_at.isoformat() if assignment.completed_at else None,
        "released_at": assignment.released_at.isoformat() if assignment.released_at else None,
        "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
    }


def assignment_batch_out(batch, assignments: list | None = None) -> dict:
    return {
        "batch_id": str(batch.id),
        "project_id": str(batch.project_id),
        "created_by_id": str(batch.created_by_id),
        "name": batch.name,
        "source_id": str(batch.source_id) if batch.source_id else None,
        "assignment_group_id": str(batch.assignment_group_id),
        "notes": batch.notes,
        "created_at": batch.created_at.isoformat(),
        "assignments": [assignment_out(a) for a in (assignments or [])],
    }


def job_out(job) -> dict:
    return {
        "job_id": str(job.id),
        "project_id": str(job.project_id),
        "source_id": str(job.source_id),
        "segment_id": str(job.segment_id),
        "job_type": job.job_type,
        "expected_revision": job.expected_revision,
        "start_seconds": job.start_seconds,
        "end_seconds": job.end_seconds,
        "config_snapshot": job.config_snapshot,
        "status": job.status,
        "attempt_n": job.attempt_n,
        "cancel_requested_at": (
            job.cancel_requested_at.isoformat() if job.cancel_requested_at else None
        ),
        "error_code": job.error_code,
        "error_message": job.error_message,
        "queued_at": job.queued_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat(),
    }


def asr_run_out(run) -> dict:
    return {
        "asr_run_id": str(run.id),
        "segment_id": str(run.segment_id),
        "project_id": str(run.project_id),
        "source_id": str(run.source_id),
        "processing_job_id": str(run.processing_job_id),
        "artifact_id": str(run.artifact_id),
        "segment_revision": run.segment_revision,
        "artifact_checksum": run.artifact_checksum,
        "provider": run.provider,
        "engine": run.engine,
        "model": run.model,
        "model_name": run.model_name,
        "model_size": run.model_size,
        "model_version": run.model_version,
        "language_requested": run.language_requested,
        "language_detected": run.language_detected,
        "task": run.task,
        "device": run.device,
        "compute_type": run.compute_type,
        "decode_params": run.decode_params,
        "text": run.text,
        "segments_json": run.segments_json,
        "words_json": run.words_json,
        "confidence_summary": run.confidence_summary,
        "is_stale_result": run.is_stale_result,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat(),
    }


def ai_assist_run_out(run) -> dict:
    return {
        "assist_run_id": str(run.id),
        "segment_id": str(run.segment_id),
        "project_id": str(run.project_id),
        "source_id": str(run.source_id),
        "created_by_user_id": str(run.created_by_user_id),
        "kind": run.kind,
        "provider": run.provider,
        "model": run.model,
        "segment_revision": run.segment_revision,
        "input_text": run.input_text,
        "output_text": run.output_text,
        "prompt_version": run.prompt_version,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat(),
        "applied_at": run.applied_at.isoformat() if run.applied_at else None,
    }


def artifact_out(artifact, segment_id) -> dict:
    return {
        "artifact_id": str(artifact.id),
        "job_id": str(artifact.job_id),
        "segment_id": str(segment_id),
        "format": artifact.format,
        "sample_rate_hz": artifact.sample_rate_hz,
        "channels": artifact.channels,
        "file_size_bytes": artifact.file_size_bytes,
        "verified": artifact.verified,
        "created_at": artifact.created_at.isoformat(),
    }


def list_out(items: list) -> dict:
    return {"items": items, "next_cursor": None, "limit": len(items)}
